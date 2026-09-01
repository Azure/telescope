#!/usr/bin/env python3

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


sys.path.insert(0, str(Path(__file__).parent))

from attach import (
    apply_resources,
    attached_volume_handles,
    build_resources,
    parse_args as parse_attach_args,
    resource_suffix,
    select_ready_nodes,
    volume_record,
    wait_attached,
    wait_ready,
)
from esan_common import (
    ManagedSan,
    canonical_handle,
    parse_handle,
    plan_shards,
    stable_san_name,
    validate_geometry,
)
from provision import (
    ArmError,
    ArmClient,
    HourlyWriteLimiter,
    SanInventory,
    desired_volume_specs,
    ensure_san,
    ensure_volume_group,
    inventory_named_sans,
    inventory_san,
    submit_volumes,
    validate_managed_inventory,
)
from repair import (
    classify_absence_once,
    delete_failed_volumes,
    desired_repair_records,
    failed_volume_records,
    recreate_volumes,
    wait_until_absent,
)
from configure_network_acls import (
    ensure_volume_group_acls,
    merged_network_acls,
    missing_subnet_ids,
)


class ShardPlannerTests(unittest.TestCase):
    def test_existing_20k_cluster_gets_one_new_20k_san(self):
        plan = plan_shards(
            existing_total=20_000,
            target_total=40_000,
            matching_sans=[],
            all_managed_indexes=[],
            shard_capacity=20_000,
        )
        self.assertEqual(1, len(plan))
        self.assertEqual(20_000, plan[0].add_count)
        self.assertEqual(20_000, plan[0].target_count)

    def test_existing_20k_cluster_gets_five_new_sans_for_120k(self):
        plan = plan_shards(
            existing_total=20_000,
            target_total=120_000,
            matching_sans=[],
            all_managed_indexes=[],
            shard_capacity=20_000,
        )
        self.assertEqual(5, len(plan))
        self.assertEqual([20_000] * 5, [item.add_count for item in plan])

    def test_partial_matching_san_is_filled_first(self):
        plan = plan_shards(
            existing_total=25_000,
            target_total=45_000,
            matching_sans=[
                ManagedSan("existing", "rg", "southeastasia", 0, "200x100", 5_000)
            ],
            all_managed_indexes=[0],
            shard_capacity=20_000,
        )
        self.assertEqual([15_000, 5_000], [item.add_count for item in plan])
        self.assertEqual([0, 1], [item.san_index for item in plan])

    def test_geometry_enforces_all_service_limits(self):
        self.assertEqual(20_000, validate_geometry(200, 100))
        for groups, volumes in ((201, 1), (1, 1_001), (200, 1_000)):
            with self.assertRaises(ValueError):
                validate_geometry(groups, volumes)

    def test_stable_san_name(self):
        first = stable_san_name("tel-esan", "cluster-uid", 0)
        self.assertEqual(first, stable_san_name("tel-esan", "cluster-uid", 0))
        self.assertNotEqual(first, stable_san_name("tel-esan", "cluster-uid", 1))
        self.assertLessEqual(len(first), 24)

    def test_shrink_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "shrinking is not supported"):
            plan_shards(
                existing_total=20_000,
                target_total=19_999,
                matching_sans=[],
                all_managed_indexes=[],
                shard_capacity=20_000,
            )


class DeterministicVolumeTests(unittest.TestCase):
    def test_full_20k_layout(self):
        specs = desired_volume_specs(
            target_count=20_000,
            volumes_per_group=100,
            existing_names=set(),
            add_count=20_000,
        )
        self.assertEqual(20_000, len(set(specs)))
        self.assertEqual(("vg-000", "vol-0000"), specs[0])
        self.assertEqual(("vg-199", "vol-0099"), specs[-1])

    def test_resume_skips_existing_slots(self):
        existing = {
            (f"vg-{index // 100:03d}", f"vol-{index % 100:04d}")
            for index in range(500)
        }
        specs = desired_volume_specs(
            target_count=1_000,
            volumes_per_group=100,
            existing_names=existing,
            add_count=500,
        )
        self.assertEqual(("vg-005", "vol-0000"), specs[0])
        self.assertEqual(("vg-009", "vol-0099"), specs[-1])

    def test_handle_round_trip(self):
        handle = canonical_handle("RG", "SAN", "VG", "VOL")
        self.assertEqual(("rg", "san", "vg", "vol"), parse_handle(handle))

    def test_limiter_rejects_invalid_bounds(self):
        with self.assertRaises(ValueError):
            HourlyWriteLimiter(0)
        with self.assertRaises(ValueError):
            HourlyWriteLimiter(3_601)
        with self.assertRaises(ValueError):
            HourlyWriteLimiter(1, 0)

    def test_reused_managed_resources_require_matching_configuration(self):
        san_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ElasticSan/elasticSans/san"
        san = {
            "id": san_id,
            "name": "san",
            "location": "southeastasia",
            "properties": {
                "sku": {"name": "Premium_LRS"},
                "availabilityZones": [],
                "baseSizeTiB": 3,
                "extendedCapacitySizeTiB": 17,
                "provisioningState": "Succeeded",
            },
        }
        group = {
            "id": f"{san_id}/volumeGroups/vg-000",
            "name": "vg-000",
            "properties": {
                "provisioningState": "Succeeded",
                "protocolType": "Iscsi",
                "encryption": "EncryptionAtRestWithPlatformKey",
                "networkAcls": {"virtualNetworkRules": [{"id": "/subnet", "action": "Allow"}]},
            },
        }
        inventory = SanInventory(
            san=ManagedSan("san", "rg", "southeastasia", 0, "200x100", 0),
            resource_id=san_id,
            tags={},
            resource=san,
            group_resources={"vg-000": group},
            groups={"vg-000": []},
        )
        validate_managed_inventory(
            inventory,
            location="southeastasia",
            base_size_tib=3,
            extended_size_tib=17,
            availability_zone="",
            subnet_ids=("/subnet",),
        )
        group["properties"]["protocolType"] = "None"
        with self.assertRaisesRegex(RuntimeError, "protocolType"):
            validate_managed_inventory(
                inventory,
                location="southeastasia",
                base_size_tib=3,
                extended_size_tib=17,
                availability_zone="",
                subnet_ids=("/subnet",),
            )


class RepairTests(unittest.TestCase):
    def test_failed_records_exclude_succeeded_volumes(self):
        inventory = type(
            "Inventory",
            (),
            {
                "san": ManagedSan("san", "rg", "southeastasia", 0, "200x100", 2),
                "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ElasticSan/elasticSans/san",
                "groups": {
                    "vg-000": [
                        {
                            "id": "/failed",
                            "name": "vol-0000",
                            "properties": {"provisioningState": "Failed", "sizeGiB": 1},
                        },
                        {
                            "id": "/succeeded",
                            "name": "vol-0001",
                            "properties": {"provisioningState": "Succeeded", "sizeGiB": 1},
                        },
                    ]
                },
            },
        )()
        records = failed_volume_records([inventory])
        self.assertEqual(1, len(records))
        self.assertEqual("vol-0000", records[0]["volume"])
        self.assertEqual(1, records[0]["size_gib"])

    def test_missing_volume_is_recovered_with_non_contiguous_san_index(self):
        inventory = type(
            "Inventory",
            (),
            {
                "san": ManagedSan("san", "rg", "southeastasia", 4, "1x2", 1),
                "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ElasticSan/elasticSans/san",
                "handles": {canonical_handle("rg", "san", "vg-000", "vol-0000")},
                "groups": {
                    "vg-000": [
                        {
                            "id": "/succeeded",
                            "name": "vol-0000",
                            "properties": {"provisioningState": "Succeeded", "sizeGiB": 1},
                        }
                    ]
                },
            },
        )()
        records = desired_repair_records(
            [inventory],
            set(),
            target_total_volumes=2,
            volumes_per_group=2,
            shard_capacity=2,
            volume_size_gib=1,
        )
        self.assertEqual([("vol-0001", "Missing")], [(item["volume"], item["state"]) for item in records])


class AsyncRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.record = {
            "san": "san",
            "san_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ElasticSan/elasticSans/san",
            "resource_group": "rg",
            "group": "vg-000",
            "volume": "vol-0000",
            "resource_id": "/failed",
            "size_gib": 1,
            "state": "Failed",
        }

    async def test_delete_and_confirm_absent_by_volume_group_list(self):
        client = type("Client", (), {})()
        client.request = AsyncMock(return_value=(202, {}, {}))
        limiter = HourlyWriteLimiter(10, 1)
        errors = await delete_failed_volumes(client, [self.record], limiter)
        self.assertEqual([], errors)
        client.request.assert_awaited_once_with(
            "DELETE",
            "/failed",
            retry_reads=False,
            retry_limiter=limiter,
        )

        client.list_all = AsyncMock(return_value=[])
        await wait_until_absent(client, [self.record], timeout_seconds=1)
        client.list_all.assert_awaited_once()

    async def test_recreate_uses_same_name_and_size(self):
        client = type("Client", (), {})()
        client.request = AsyncMock(return_value=(202, {}, {}))
        limiter = HourlyWriteLimiter(10, 1)
        with patch("repair.asyncio.sleep", new=AsyncMock()):
            errors = await recreate_volumes(client, [self.record], limiter)
        self.assertEqual([], errors)
        resource_id = client.request.await_args.args[1]
        self.assertTrue(resource_id.endswith("/volumeGroups/vg-000/volumes/vol-0000"))
        self.assertEqual({"properties": {"sizeGiB": 1}}, client.request.await_args.args[2])

    async def test_absence_is_tracked_per_volume_after_partial_delete(self):
        sibling = {**self.record, "volume": "vol-0001", "resource_id": "/failed-sibling"}
        client = type("Client", (), {})()
        client.list_all = AsyncMock(
            return_value=[{"name": "vol-0001", "properties": {"provisioningState": "Failed"}}]
        )
        with patch("repair.time.monotonic", side_effect=[0, 0, 2]), patch(
            "repair.asyncio.sleep", new=AsyncMock()
        ):
            absent, present = await wait_until_absent(
                client, [self.record, sibling], timeout_seconds=1
            )
        self.assertEqual({("san", "vg-000", "vol-0000")}, absent)
        self.assertEqual({("san", "vg-000", "vol-0001")}, present)

    async def test_delete_error_is_classified_without_polling(self):
        sibling = {**self.record, "volume": "vol-0001", "resource_id": "/failed-sibling"}
        client = type("Client", (), {})()
        client.list_all = AsyncMock(return_value=[{"name": "vol-0001"}])
        absent, present = await classify_absence_once(client, [self.record, sibling])
        self.assertEqual({("san", "vg-000", "vol-0000")}, absent)
        self.assertEqual({("san", "vg-000", "vol-0001")}, present)
        client.list_all.assert_awaited_once()


class AsyncArmClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_text_throttle_retries_with_millisecond_header(self):
        class Response:
            def __init__(self, status, text, headers):
                self.status = status
                self._text = text
                self.headers = headers

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def text(self):
                return self._text

        class Session:
            def __init__(self):
                self.responses = iter(
                    [
                        Response(429, "temporarily throttled", {"x-ms-retry-after-ms": "1500"}),
                        Response(200, '{"value": []}', {}),
                    ]
                )

            def request(self, *_args, **_kwargs):
                return next(self.responses)

        client = ArmClient("sub")
        client.session = Session()
        client._access_token = AsyncMock(return_value="token")
        with patch("provision.asyncio.sleep", new=AsyncMock()) as sleep:
            status, body, _ = await client.request("GET", "/resource")
        self.assertEqual(200, status)
        self.assertEqual([], body["value"])
        sleep.assert_awaited_once_with(1.5)

    async def test_put_throttle_retries_and_counts_retry_write(self):
        class Response:
            def __init__(self, status, text, headers):
                self.status = status
                self._text = text
                self.headers = headers

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def text(self):
                return self._text

        class Session:
            def __init__(self):
                self.responses = iter(
                    [
                        Response(429, "throttled", {"retry-after": "1"}),
                        Response(201, "{}", {}),
                    ]
                )

            def request(self, *_args, **_kwargs):
                return next(self.responses)

        client = ArmClient("sub")
        client.session = Session()
        client._access_token = AsyncMock(return_value="token")
        limiter = type("Limiter", (), {})()
        limiter.acquire = AsyncMock()
        with patch("provision.asyncio.sleep", new=AsyncMock()) as sleep:
            status, _, _ = await client.request(
                "PUT",
                "/resource",
                {},
                retry_reads=False,
                retry_limiter=limiter,
            )
        self.assertEqual(201, status)
        sleep.assert_awaited_once_with(1.0)
        limiter.acquire.assert_awaited_once_with(1)


class AsyncProvisionWriteLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_twenty_first_concurrent_write_waits_for_next_burst_window(self):
        limiter = HourlyWriteLimiter(100, burst_limit=20, burst_window_seconds=1.1)
        current_time = 0.0

        async def advance_clock(delay: float) -> None:
            nonlocal current_time
            current_time += delay

        limiter._clock = lambda: current_time
        limiter._sleep = AsyncMock(side_effect=advance_clock)
        await asyncio.gather(*(limiter.acquire(1) for _ in range(21)))
        limiter._sleep.assert_awaited_once_with(1.1)

    async def test_new_san_consumes_write_budget(self):
        client = type("Client", (), {"subscription_id": "sub"})()
        client.request = AsyncMock(
            side_effect=[
                ArmError(404, "GET", "https://example.invalid/san", "not found"),
                (202, {}, {}),
            ]
        )
        limiter = type("Limiter", (), {})()
        limiter.acquire = AsyncMock()
        with patch("provision.wait_succeeded", new=AsyncMock()):
            await ensure_san(
                client,
                limiter,
                resource_group="rg",
                name="san",
                location="southeastasia",
                base_size_tib=3,
                extended_size_tib=17,
                availability_zone="2",
                tags={"managed": "true"},
            )
        limiter.acquire.assert_awaited_once_with(1)
        payload = client.request.await_args_list[1].args[2]
        self.assertNotIn("sku", payload)
        self.assertNotIn("zones", payload)
        self.assertEqual(
            {"name": "Premium_LRS", "tier": "Premium"},
            payload["properties"]["sku"],
        )
        self.assertEqual(["2"], payload["properties"]["availabilityZones"])

    async def test_volume_batch_acquires_one_burst_slot_per_put(self):
        client = type("Client", (), {})()
        client.request = AsyncMock(return_value=(201, {}, {}))
        limiter = type("Limiter", (), {})()
        limiter.acquire = AsyncMock()
        accepted, errors = await submit_volumes(
            client,
            san_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ElasticSan/elasticSans/san",
            specs=[("vg-000", f"vol-{index:04d}") for index in range(100)],
            volume_size_gib=1,
            batch_size=100,
            batch_delay_seconds=0,
            limiter=limiter,
        )
        self.assertEqual(100, len(accepted))
        self.assertEqual([], errors)
        self.assertEqual(100, limiter.acquire.await_count)
        self.assertTrue(all(call.args == (1,) for call in limiter.acquire.await_args_list))

    async def test_new_volume_group_consumes_write_budget(self):
        client = type("Client", (), {})()
        client.request = AsyncMock(return_value=(202, {}, {}))
        limiter = type("Limiter", (), {})()
        limiter.acquire = AsyncMock()
        with patch("provision.wait_succeeded", new=AsyncMock()):
            await ensure_volume_group(
                client,
                limiter,
                san_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ElasticSan/elasticSans/san",
                name="vg-000",
                subnet_ids=("/subnet",),
            )
        limiter.acquire.assert_awaited_once_with(1)


class AttachmentRendererTests(unittest.TestCase):
    def setUp(self):
        self.volume = {
            "name": "vol-0000",
            "properties": {
                "provisioningState": "Succeeded",
                "sizeGiB": 1,
                "storageTarget": {
                    "targetIqn": "iqn.test",
                    "targetPortalHostname": "target.test",
                    "targetPortalPort": 3260,
                },
            },
        }

    def test_only_mount_ready_volumes_are_selected(self):
        record = volume_record("rg", "san", "vg-000", self.volume)
        self.assertIsNotNone(record)
        failed = {**self.volume, "properties": {**self.volume["properties"], "provisioningState": "Failed"}}
        self.assertIsNone(volume_record("rg", "san", "vg-000", failed))

    def test_attachment_cpu_request_defaults_to_300m(self):
        with patch.object(
            sys,
            "argv",
            [
                "attach.py",
                "--cluster-id",
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks",
                "--kubeconfig",
                "/tmp/kubeconfig",
                "--results-dir",
                "/tmp/results",
            ],
        ):
            args = parse_attach_args()
        self.assertEqual("300m", args.cpu_request)

    def test_attached_handles_only_include_successful_volume_attachments(self):
        attached_handle = "rg#san#vg#a"
        pending_handle = "rg#san#vg#b"
        volume_attachments = {
            "items": [
                {
                    "spec": {
                        "attacher": "san.csi.azure.com",
                        "source": {
                            "persistentVolumeName": f"tesan-pv-{resource_suffix(attached_handle)}"
                        },
                    },
                    "status": {"attached": True},
                },
                {
                    "spec": {
                        "attacher": "san.csi.azure.com",
                        "source": {
                            "persistentVolumeName": f"tesan-pv-{resource_suffix(pending_handle)}"
                        },
                    },
                    "status": {"attached": False},
                },
            ]
        }
        with patch(
            "attach.kubectl_json", return_value=volume_attachments
        ) as kubectl_json_mock:
            handles = attached_volume_handles(
                "/tmp/kubeconfig", {attached_handle, pending_handle}
            )
        self.assertEqual({attached_handle}, handles)
        # PVs are derived locally, so only VolumeAttachments are listed (no get pv).
        kubectl_json_mock.assert_called_once()
        self.assertNotIn("pv", kubectl_json_mock.call_args.args[1])

    def test_resources_are_static_retain_and_cluster_scoped(self):
        record = volume_record("rg", "san", "vg-000", self.volume)
        assert record
        _, resources = build_resources(
            record,
            namespace_prefix="test-esan",
            node_label_key="target",
            node_label_value="cluster123",
            image="busybox",
            cpu_request="10m",
            memory_request="32Mi",
        )
        pv = next(item for item in resources if item["kind"] == "PersistentVolume")
        pod = next(item for item in resources if item["kind"] == "Pod")
        self.assertEqual("Retain", pv["spec"]["persistentVolumeReclaimPolicy"])
        self.assertEqual("san.csi.azure.com", pv["spec"]["csi"]["driver"])
        self.assertEqual("/data", pod["spec"]["containers"][0]["volumeMounts"][0]["mountPath"])
        self.assertEqual(
            "cluster123",
            pod["spec"]["topologySpreadConstraints"][0]["labelSelector"][
                "matchLabels"
            ]["telescope-cluster"],
        )
        self.assertEqual(resource_suffix(record["handle"]), pv["metadata"]["name"].removeprefix("tesan-pv-"))
        self.assertEqual(
            f"test-esan-{resource_suffix(record['handle'])[:2]}",
            pod["metadata"]["namespace"],
        )

    def test_apply_resources_flushes_final_partial_batch(self):
        record = volume_record("rg", "san", "vg-000", self.volume)
        assert record
        args = SimpleNamespace(
            namespace_prefix="telescope-esan",
            node_label_key="telescope-esan-attach",
            pod_image="image",
            cpu_request="10m",
            memory_request="32Mi",
            apply_batch_size=100,
        )
        with patch("attach.ensure_namespace") as ensure_namespace, patch(
            "attach.kubectl"
        ) as kubectl_apply:
            apply_resources(
                kubeconfig="/tmp/kubeconfig",
                records=[record],
                args=args,
                node_label_value="cluster",
            )
        ensure_namespace.assert_called_once()
        kubectl_apply.assert_called_once()
        self.assertEqual("apply", kubectl_apply.call_args.args[1][0])

    def test_readiness_ignores_extra_pods_from_larger_prior_stage(self):
        payload = {
            "items": [
                {
                    "metadata": {"name": name},
                    "status": {
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                }
                for name in ("selected-a", "selected-b", "extra-old")
            ]
        }
        with patch("attach.kubectl_json", return_value=payload):
            status = wait_ready(
                "/tmp/kubeconfig", "cluster123", {"selected-a", "selected-b"}, 1
            )
        self.assertEqual(3, status["managed_total"])
        self.assertEqual(2, status["selected"])
        self.assertEqual(2, status["ready"])

    def test_node_selection_requires_capacity_and_prefers_least_loaded(self):
        def node(name):
            return {
                "metadata": {"name": name, "labels": {"kubernetes.io/os": "linux"}},
                "spec": {},
                "status": {
                    "allocatable": {"pods": "250"},
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            }

        nodes = {"items": [node("loaded"), node("eligible-b"), node("eligible-a")]}
        pods = {"items": []}
        for name, count in (("loaded", 100), ("eligible-b", 20), ("eligible-a", 5)):
            pods["items"].extend({"spec": {"nodeName": name}} for _ in range(count))
        with patch("attach.kubectl_json", side_effect=[nodes, pods]):
            selected = select_ready_nodes(
                kubeconfig="/tmp/kubeconfig",
                selector="pool=user",
                required=2,
                pods_per_node=150,
                pod_slot_headroom=10,
            )
        self.assertEqual(["eligible-a", "eligible-b"], selected)

    def test_node_selection_excludes_windows_nodes(self):
        windows = {
            "metadata": {"name": "windows", "labels": {"kubernetes.io/os": "windows"}},
            "spec": {},
            "status": {
                "allocatable": {"pods": "250"},
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }
        with patch("attach.kubectl_json", side_effect=[{"items": [windows]}, {"items": []}]):
            with self.assertRaises(RuntimeError):
                select_ready_nodes(
                    kubeconfig="/tmp/kubeconfig",
                    selector="pool=user",
                    required=1,
                    pods_per_node=150,
                    pod_slot_headroom=10,
                )

    def test_wait_attached_requires_all_expected_handles(self):
        with patch(
            "attach.attached_volume_handles",
            side_effect=[{"rg#san#vg#a"}, {"rg#san#vg#a", "rg#san#vg#b"}],
        ), patch("attach.time.sleep"):
            attached = wait_attached(
                "/tmp/kubeconfig",
                {"rg#san#vg#a", "rg#san#vg#b"},
                1,
            )
        self.assertEqual(2, attached)


class InventoryNamedSansTests(unittest.IsolatedAsyncioTestCase):
    async def test_named_san_selected_without_managed_tags(self):
        san_id = (
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.ElasticSan/elasticSans/exp"
        )
        sans = [
            {"id": san_id, "name": "exp", "location": "southeastasia", "tags": None},
            {
                "id": san_id.replace("/exp", "/other"),
                "name": "other",
                "location": "southeastasia",
                "tags": None,
            },
        ]

        async def fake_list_all(resource_id):
            if resource_id.endswith("/elasticSans"):
                return sans
            if resource_id.endswith("/volumeGroups"):
                return [{"id": f"{san_id}/volumeGroups/sdk-vg-000", "name": "sdk-vg-000"}]
            if resource_id.endswith("/volumes"):
                return [{"name": "vol", "properties": {"provisioningState": "Succeeded"}}]
            return []

        client = SimpleNamespace(
            subscription_id="sub", list_all=AsyncMock(side_effect=fake_list_all)
        )
        inventories = await inventory_named_sans(client, ["EXP"])
        self.assertEqual(1, len(inventories))
        self.assertEqual("exp", inventories[0].san.name)
        self.assertEqual(1, inventories[0].san.volume_count)


class NetworkAclHelperTests(unittest.TestCase):
    @staticmethod
    def _vg(rules):
        return {
            "id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ElasticSan"
            "/elasticSans/e/volumeGroups/sdk-vg-000",
            "name": "sdk-vg-000",
            "properties": {"networkAcls": {"virtualNetworkRules": rules}},
        }

    def test_missing_subnet_ids_is_case_insensitive(self):
        vg = self._vg([{"id": "/subs/AKS", "action": "Allow"}])
        self.assertEqual([], missing_subnet_ids(vg, ("/subs/aks",)))
        self.assertEqual(["/subs/new"], missing_subnet_ids(vg, ("/subs/aks", "/subs/new")))

    def test_missing_subnet_ids_handles_absent_acls(self):
        self.assertEqual(["/subs/a"], missing_subnet_ids({"properties": {}}, ("/subs/a",)))

    def test_merged_network_acls_preserves_existing_rules(self):
        vg = self._vg([{"id": "/subs/keep", "action": "Allow"}])
        merged = merged_network_acls(vg, ["/subs/new"])
        self.assertEqual(
            ["/subs/keep", "/subs/new"],
            [rule["id"] for rule in merged["virtualNetworkRules"]],
        )


class AsyncNetworkAclTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _vg(rules):
        return {
            "id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ElasticSan"
            "/elasticSans/e/volumeGroups/sdk-vg-000",
            "name": "sdk-vg-000",
            "properties": {"networkAcls": {"virtualNetworkRules": rules}},
        }

    async def test_skips_when_subnet_already_allowed(self):
        client = SimpleNamespace(request=AsyncMock())
        limiter = SimpleNamespace(acquire=AsyncMock())
        vg = self._vg([{"id": "/subs/aks", "action": "Allow"}])
        action = await ensure_volume_group_acls(
            client, limiter, volume_group=vg, subnet_ids=("/subs/aks",)
        )
        self.assertEqual("skipped", action)
        client.request.assert_not_awaited()
        limiter.acquire.assert_not_awaited()

    async def test_patches_missing_subnet_and_preserves_existing(self):
        client = SimpleNamespace(request=AsyncMock(return_value=(200, {}, {})))
        limiter = SimpleNamespace(acquire=AsyncMock())
        vg = self._vg([{"id": "/subs/keep", "action": "Allow"}])
        action = await ensure_volume_group_acls(
            client, limiter, volume_group=vg, subnet_ids=("/subs/aks",)
        )
        self.assertEqual("updated", action)
        limiter.acquire.assert_awaited_once()
        self.assertEqual("PATCH", client.request.await_args.args[0])
        self.assertEqual(vg["id"], client.request.await_args.args[1])
        body = client.request.await_args.args[2]
        self.assertEqual(
            ["/subs/keep", "/subs/aks"],
            [rule["id"] for rule in body["properties"]["networkAcls"]["virtualNetworkRules"]],
        )


if __name__ == "__main__":
    unittest.main()