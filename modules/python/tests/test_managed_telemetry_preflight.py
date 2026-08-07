"""Tests for the early managed-telemetry preflight embedded in
steps/setup-tests.yml ("Preflight ClusterMesh managed-telemetry (control-plane
metrics)"). This step runs BEFORE Terraform (see jobs/competitive-test.yml:
setup-tests.yml precedes provision-resources.yml) and must fail fast on:
  - a UI-selected subscription mismatch
  - the AzureMonitorMetricsControlPlanePreview feature not being Registered
    (unless AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW=true, in which case the
    later configure step is responsible for registering it)
  - the Microsoft.Monitor accounts/metricsContainers 2025-05-03-preview
    api-version/resource type genuinely being unsupported for the
    subscription when requested ingestion limits exceed the 1,000,000
    platform default (NoRegisteredProviderFound/InvalidApiVersion/
    UnsupportedApiVersion/unsupported resource type), or an
    authorization/subscription error (AuthorizationFailed/Forbidden/
    subscription errors) or other unexpected error while probing it --
    while a ResourceNotFound/NotFound/404 on the probed AMW's specific
    metricsContainers/default child is only informational/inconclusive
    (that AMW may simply never have had the child created) and must NOT
    block the run; configure-time creation/verification remains
    authoritative
  - a regional Azure Monitor workspace (AMW) count that would exceed
    AKS_AMW_REGIONAL_WORKSPACE_LIMIT once this run's desired AMW count is added
  - malformed numeric inputs

These tests extract the exact script embedded in steps/setup-tests.yml (rather
than duplicating it) and exercise it with a fake `az` on PATH plus the real
`jq` binary -- consistent with how test_clustermesh_validate_resources_kubeconfig.py
exercises the fetch-kubeconfig.sh heredoc extracted from validate-resources.yml,
and how test_clustermesh_scale.py::TestNodeChurnerScript / test_clustermesh_mock_
provision_script.py fake `az`/`kubectl` for vendored shell scripts in this repo.
"""

import json
import os
import stat
import subprocess
import textwrap
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
YAML_PATH = REPO_ROOT / "steps" / "setup-tests.yml"
STEP_DISPLAY_NAME = "Preflight ClusterMesh managed-telemetry (control-plane metrics)"


def _load_steps():
    with open(YAML_PATH, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc["steps"]


def _step(steps, display_name):
    for step in steps:
        if step.get("displayName") == display_name:
            return step
    raise AssertionError(f"no step with displayName={display_name!r} found in {YAML_PATH}")


def test_preflight_step_is_gated_on_control_plane_metrics_enabled_and_scenario():
    """Static wiring check: the step must only run for clustermesh scenarios
    and only when AKS_CONTROL_PLANE_METRICS_ENABLED is exactly 'true', and
    must resolve REGION from the template parameter (same pattern as the
    "Preflight ClusterMesh VM quota" step directly above it)."""
    step = _step(_load_steps(), STEP_DISPLAY_NAME)
    condition = step["condition"]
    assert "startsWith(variables['SCENARIO_NAME'], 'clustermesh')" in condition
    assert "eq(variables['AKS_CONTROL_PLANE_METRICS_ENABLED'], 'true')" in condition
    assert step["env"]["REGION"] == "${{ parameters.region }}"


def test_preflight_script_passes_bash_syntax_check():
    script = _step(_load_steps(), STEP_DISPLAY_NAME)["script"]
    result = subprocess.run(
        ["bash", "-n", "-c", script],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode == 0, (
        f"bash -n failed: stdout={result.stdout} stderr={result.stderr}"
    )


# Fake `az` CLI: driven entirely by env vars so each test can script exactly
# what each az subcommand returns, with no real network/Azure dependency.
#   AZ_ACCOUNT_ID              value returned by `az account show --query id -o tsv`
#   AZ_FEATURE_STATE           value returned by `az feature show ...` (empty = query fails)
#   AZ_MONITOR_ACCOUNTS_JSON   JSON array returned by `az monitor account list`
#   AZ_RESOURCE_SHOW_FAILS     "true" makes the direct ARM
#                              `az resource show --ids .../metricsContainers/default`
#                              probe fail with AZ_RESOURCE_SHOW_STDERR/
#                              AZ_RESOURCE_SHOW_EXIT_CODE (simulates any ARM
#                              error -- not-found, unsupported api-version/
#                              resource type, authorization/subscription, or
#                              some other unexpected failure)
#   AZ_RESOURCE_SHOW_STDERR    stderr text the fake `az resource show` prints
#                              when AZ_RESOURCE_SHOW_FAILS=true (default: a
#                              generic, uncategorized failure message)
#   AZ_RESOURCE_SHOW_EXIT_CODE exit code the fake `az resource show` returns
#                              when AZ_RESOURCE_SHOW_FAILS=true (default: 1)
#   AZ_CALL_LOG                path this fake `az` appends one line to per call,
#                              so tests can assert which subcommands ran
FAKE_AZ = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -u
    args="$*"
    if [ -n "${AZ_CALL_LOG:-}" ]; then echo "$args" >> "$AZ_CALL_LOG"; fi
    case "$args" in
      *"account show --query id -o tsv"*)
        echo "${AZ_ACCOUNT_ID:-11111111-1111-1111-1111-111111111111}"
        ;;
      *"feature show"*)
        if [ -z "${AZ_FEATURE_STATE:-}" ]; then
          echo "fake az: feature show query failed" >&2
          exit 1
        fi
        echo "$AZ_FEATURE_STATE"
        ;;
      *"resource show --ids "*)
        if [ "${AZ_RESOURCE_SHOW_FAILS:-false}" = "true" ]; then
          echo "${AZ_RESOURCE_SHOW_STDERR:-fake az: resource show query failed}" >&2
          exit "${AZ_RESOURCE_SHOW_EXIT_CODE:-1}"
        fi
        echo '{}'
        ;;
      *"monitor account list --output json"*)
        printf '%s\\n' "${AZ_MONITOR_ACCOUNTS_JSON:-[]}"
        ;;
      *)
        echo "fake az: unsupported invocation: $*" >&2
        exit 2
        ;;
    esac
""")


class ManagedTelemetryPreflightTestCase(unittest.TestCase):
    """Extracts the real embedded script once, then runs it per-test against
    a fresh fake `az` + tmp dir, with a baseline env representing a healthy
    n=100-shaped run (2 clusters/workspace, rotation disabled, defaults
    otherwise) that each test perturbs to exercise one failure mode at a
    time."""

    # Matches build_workspace_assignments()'s cpw>1 "<prefix>-shard-NNN"
    # naming in configure-managed-prometheus.sh.
    @staticmethod
    def _shard_name(prefix, shard_number):
        return f"{prefix}-shard-{shard_number:03d}"

    # Matches build_workspace_assignments()'s cpw==1 "<prefix>-mesh-<i>"
    # naming (cluster roles are "mesh-1".."mesh-N").
    @staticmethod
    def _mesh_name(prefix, cluster_index):
        return f"{prefix}-mesh-{cluster_index}"

    @classmethod
    def setUpClass(cls):
        cls.script = _step(_load_steps(), STEP_DISPLAY_NAME)["script"]

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        td = self.tmp.name

        self.bin_dir = os.path.join(td, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        fake_az_path = os.path.join(self.bin_dir, "az")
        with open(fake_az_path, "w", encoding="utf-8") as f:
            f.write(FAKE_AZ)
        st = os.stat(fake_az_path)
        os.chmod(fake_az_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        self.call_log = os.path.join(td, "az_call_log")
        self.amw_name_prefix = "cmsh-scale-test-n100-amw"

    def _account(self, name, location):
        return {
            "name": name,
            "location": location,
            "id": (
                "/subscriptions/11111111-1111-1111-1111-111111111111/"
                f"resourceGroups/rg/providers/Microsoft.Monitor/accounts/{name}"
            ),
        }

    def _run(self, env_overrides=None):
        env = os.environ.copy()
        env["PATH"] = self.bin_dir + os.pathsep + env["PATH"]
        env["AZ_CALL_LOG"] = self.call_log
        # Healthy n=100-shaped baseline: subscription matches, feature
        # Registered, ingestion limits at the 1M default (no preview API
        # needed), rotation disabled, 100 clusters sharded 2/workspace = 50
        # desired, 3 pre-existing regional workspaces (none matching this
        # run's target shard names) -> 53, comfortably under 100.
        env.update({
            "AZURE_SUBSCRIPTION_ID": "11111111-1111-1111-1111-111111111111",
            "AZ_ACCOUNT_ID": "11111111-1111-1111-1111-111111111111",
            "REGION": "eastus2euap",
            "CLUSTER_COUNT": "100",
            "AKS_AMW_CLUSTERS_PER_WORKSPACE": "2",
            "AKS_AMW_REGIONAL_WORKSPACE_LIMIT": "100",
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "1000000",
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "1000000",
            "AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW": "false",
            "AKS_AMW_ROTATION_ENABLED": "false",
            "AKS_CONTROL_PLANE_AMW_NAME_PREFIX": self.amw_name_prefix,
            "AZ_FEATURE_STATE": "Registered",
            "AZ_MONITOR_ACCOUNTS_JSON": json.dumps([
                self._account("other-workspace-1", "eastus2euap"),
                self._account("other-workspace-2", "eastus2euap"),
                self._account("other-workspace-3", "eastus2euap"),
                self._account("westus2-workspace", "westus2"),
            ]),
        })
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", "-c", self.script],
            capture_output=True, text=True, env=env, check=False, timeout=30,
        )

    def _calls(self):
        if not os.path.exists(self.call_log):
            return []
        with open(self.call_log, "r", encoding="utf-8") as f:
            return [line for line in f.read().splitlines() if line]


class TestSelectedSubscriptionWiring(ManagedTelemetryPreflightTestCase):
    def test_matching_subscription_passes(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mismatched_subscription_fails_clearly(self):
        result = self._run({"AZ_ACCOUNT_ID": "22222222-2222-2222-2222-222222222222"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Expected Azure subscription", result.stderr)
        self.assertIn("11111111-1111-1111-1111-111111111111", result.stderr)
        self.assertIn("22222222-2222-2222-2222-222222222222", result.stderr)

    def test_subscription_check_is_case_insensitive(self):
        result = self._run({
            "AZURE_SUBSCRIPTION_ID": "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
            "AZ_ACCOUNT_ID": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        })
        self.assertEqual(result.returncode, 0, result.stderr)


class TestFeatureRegistrationGate(ManagedTelemetryPreflightTestCase):
    def test_registered_feature_passes(self):
        result = self._run({"AZ_FEATURE_STATE": "Registered"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("is Registered", result.stdout)

    def test_unregistered_feature_fails_with_registration_instructions(self):
        result = self._run({"AZ_FEATURE_STATE": "NotRegistered"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AzureMonitorMetricsControlPlanePreview", result.stderr)
        self.assertIn("not Registered", result.stderr)
        self.assertIn("az feature register", result.stderr)
        self.assertIn("AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW=true", result.stderr)

    def test_unknown_feature_state_fails(self):
        """`az feature show` query failure (empty state) must fail closed,
        not be treated as an implicit pass."""
        result = self._run({"AZ_FEATURE_STATE": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown, not Registered", result.stderr)

    def test_register_preview_true_skips_hard_requirement_without_registering(self):
        """When AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW=true, the preflight
        must NOT itself call `az feature register` (that is the configure
        step's job) -- it should just report that the later step will
        register the feature and continue."""
        result = self._run({
            "AKS_CONTROL_PLANE_METRICS_REGISTER_PREVIEW": "true",
            "AZ_FEATURE_STATE": "",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("will register", result.stdout)
        self.assertIn("Skipping the hard Registered-state requirement", result.stdout)
        calls = self._calls()
        self.assertFalse(
            any("feature show" in c or "feature register" in c for c in calls),
            f"preflight must not query/trigger feature registration itself: {calls}",
        )


class TestMetricsContainerDirectArmProbe(ManagedTelemetryPreflightTestCase):
    """Covers the direct ARM verification against an existing regional AMW's
    `<id>/metricsContainers/default` (replacing the old, unreliable
    `az provider show` enumeration -- that command never lists
    metricsContainers as a nested resourceType, so it always reported
    "not exposed" regardless of actual subscription capability).

    The probed AMW is arbitrary, and default-1M workspaces may never have
    had a metricsContainers/default child created for them, so the probe's
    stderr/exit code are captured explicitly and categorized:
      - success                                        -> capability confirmed
      - ResourceNotFound/NotFound/404 for the child     -> informational,
        inconclusive, continue (configure-time creation/verification
        remains authoritative)
      - NoRegisteredProviderFound/InvalidApiVersion/
        UnsupportedApiVersion/unsupported resource type -> fail early
      - AuthorizationFailed/Forbidden/subscription
        errors, or any other unexpected error           -> fail early with
        a sanitized, actionable message
    """

    def test_check_skipped_at_default_ingestion_limits(self):
        """At the 1,000,000 platform default, the direct ARM probe (and the
        underlying `az resource show` call) must not run at all -- only the
        unconditional `az monitor account list` call (needed by the quota
        check below) should happen."""
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "1000000",
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "1000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertFalse(
            any("resource show" in c for c in calls),
            f"resource show should be skipped under the 1M default: {calls}",
        )
        self.assertTrue(
            any("monitor account list" in c for c in calls),
            f"monitor account list should still run for the quota check: {calls}",
        )

    def test_probe_passes_against_existing_amw(self):
        """When an AMW already exists in $REGION, the probe must issue a
        direct `az resource show --ids <that AMW id>/metricsContainers/
        default --api-version 2025-05-03-preview` call and pass when ARM
        serves it successfully."""
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Verified Microsoft.Monitor/accounts/metricsContainers api-version "
            "2025-05-03-preview directly against existing AMW",
            result.stdout,
        )
        self.assertIn("other-workspace-1", result.stdout)
        calls = self._calls()
        self.assertTrue(
            any(
                "resource show --ids " in c
                and "/metricsContainers/default" in c
                and "--api-version 2025-05-03-preview" in c
                for c in calls
            ),
            f"expected a direct metricsContainers ARM probe call: {calls}",
        )

    def test_probe_fails_on_unexpected_uncategorized_error(self):
        """A real ARM failure that doesn't match any of the recognized
        not-found / unsupported-surface / authorization error categories
        must still be fatal, reported with a sanitized, actionable message
        rather than silently passing or hanging."""
        result = self._run({
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": "fake az: some unrecognized transient failure",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("2025-05-03-preview", result.stderr)
        self.assertIn("Unexpected error", result.stderr)
        self.assertIn("some unrecognized transient failure", result.stderr)
        self.assertIn("other-workspace-1", result.stderr)

    def test_resource_not_found_on_child_is_informational_and_continues(self):
        """A ResourceNotFound on the specific metricsContainers/default
        child of an arbitrary existing AMW is inconclusive, not fatal: a
        default-1M workspace may simply never have had that child created.
        The preflight must log this as informational and continue --
        configure-time creation/verification remains authoritative."""
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": (
                "(ResourceNotFound) The Resource "
                "'Microsoft.Monitor/accounts/other-workspace-1/metricsContainers/default' "
                "under resource group 'rg' was not found.\nCode: ResourceNotFound"
            ),
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ResourceNotFound", result.stdout)
        self.assertIn("informational, inconclusive", result.stdout)
        self.assertIn("does NOT indicate", result.stdout)
        self.assertIn("other-workspace-1", result.stdout)

    def test_plain_not_found_variant_is_informational_and_continues(self):
        """Same as ResourceNotFound, but for a plain 'NotFound' error code
        variant -- must also be treated as informational, not fatal."""
        result = self._run({
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": "Code: NotFound\nMessage: the child resource was not found.",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("informational, inconclusive", result.stdout)

    def test_plain_404_is_informational_and_continues(self):
        """A bare HTTP 404 (no ARM error code text) must also be treated as
        informational/inconclusive, not fatal."""
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": "Operation returned an invalid status 'Not Found' (404)",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("informational, inconclusive", result.stdout)

    def test_no_registered_provider_found_fails_early(self):
        """NoRegisteredProviderFound means the resource type genuinely
        isn't registered/exposed for this subscription -- this must fail
        fast, unlike a plain not-found on the probed child."""
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": (
                "(NoRegisteredProviderFound) No registered resource provider found "
                "for location 'eastus2euap' and API version '2025-05-03-preview' for "
                "type 'accounts/metricsContainers'."
            ),
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("2025-05-03-preview", result.stderr)
        self.assertIn("does not support that resource type/api-version", result.stderr)
        self.assertIn("NoRegisteredProviderFound", result.stderr)

    def test_invalid_api_version_fails_early(self):
        """InvalidApiVersion must fail fast: the requested preview
        api-version is genuinely not usable, not merely absent on one AMW."""
        result = self._run({
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": "(InvalidApiVersion) The api-version '2025-05-03-preview' is invalid.",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not support that resource type/api-version", result.stderr)

    def test_unsupported_api_version_fails_early(self):
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": "(UnsupportedApiVersion) api-version is not supported for this resource type.",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not support that resource type/api-version", result.stderr)

    def test_unsupported_resource_type_fails_early(self):
        result = self._run({
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": "(ResourceTypeNotSupported) resource type is not supported.",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not support that resource type/api-version", result.stderr)

    def test_authorization_failed_fails_early_with_sanitized_message(self):
        """AuthorizationFailed must fail fast with an actionable message,
        and must not leak the raw GUIDs from the underlying az error."""
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": (
                "(AuthorizationFailed) The client '11111111-2222-3333-4444-555555555555' "
                "with object id '11111111-2222-3333-4444-555555555555' does not have "
                "authorization to perform action 'Microsoft.Monitor/accounts/read' over "
                "scope '/subscriptions/11111111-1111-1111-1111-111111111111'."
            ),
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authorization/subscription error", result.stderr)
        self.assertIn("Reader access", result.stderr)
        self.assertIn("AuthorizationFailed", result.stderr)
        self.assertNotIn("11111111-2222-3333-4444-555555555555", result.stderr)
        self.assertIn("[redacted-guid]", result.stderr)

    def test_forbidden_fails_early(self):
        result = self._run({
            "AKS_AMW_MAX_EVENTS_PER_MINUTE": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": "(Forbidden) the request is forbidden.",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authorization/subscription error", result.stderr)

    def test_subscription_not_found_fails_early(self):
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "AZ_RESOURCE_SHOW_FAILS": "true",
            "AZ_RESOURCE_SHOW_STDERR": "(SubscriptionNotFound) the subscription could not be found.",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authorization/subscription error", result.stderr)

    def test_probe_skipped_without_false_failure_when_no_existing_amw_in_region(self):
        """When no AMW exists yet in $REGION, the capability genuinely
        cannot be probed. This must be logged as an informational skip --
        NOT a fatal error -- since configure-managed-prometheus.sh performs
        its own authoritative check once it creates the first AMW."""
        result = self._run({
            "AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2000000",
            "REGION": "westus2",
            "AKS_AMW_REGIONAL_WORKSPACE_LIMIT": "51",
            # Only the westus2-workspace account (no id needed for the
            # probe path since it's still present) exists in westus2 in the
            # baseline fixture; force "no existing AMW" by emptying the
            # region's account list entirely for this test.
            "AZ_MONITOR_ACCOUNTS_JSON": json.dumps([
                self._account("other-workspace-1", "eastus2euap"),
            ]),
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No existing Azure Monitor workspace found in westus2", result.stdout)
        self.assertIn(
            "cannot be probed until configure-managed-prometheus.sh creates the first AMW",
            result.stdout,
        )
        calls = self._calls()
        self.assertFalse(
            any("resource show" in c for c in calls),
            f"resource show must not run when there is no AMW to probe against: {calls}",
        )


class TestRegionalWorkspaceQuotaRotationDisabled(ManagedTelemetryPreflightTestCase):
    """Rotation-disabled (n=100-style) missing-workspace-name math: naming is
    fully deterministic, so the preflight can precisely compute which target
    workspace names are still missing from the region instead of assuming
    every desired workspace is newly created."""

    def test_first_run_all_target_workspaces_missing(self):
        # 100 clusters / 2 per workspace = 50 desired; none of the 3
        # existing regional accounts match a target shard-NNN name, so all
        # 50 are "missing" -> existing 3 + missing 50 = 53 <= 100.
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("desired_workspaces=50", result.stdout)
        self.assertIn("existing regional Microsoft.Monitor/accounts=3", result.stdout)
        self.assertIn("missing_workspaces=50", result.stdout)
        self.assertIn("projected_total=53", result.stdout)
        self.assertIn("limit=100", result.stdout)

    def test_rerun_with_all_base_workspaces_already_existing_is_allowed(self):
        """The core n=100 rerun scenario: the same 50 shard-NNN workspaces
        from a prior run already exist. Naively adding desired (50) on top
        of existing (53) would wrongly project 103 and block the rerun; the
        missing-name math must recognize 0 new workspaces are needed and
        allow it through."""
        prefix = self.amw_name_prefix
        accounts = [
            self._account("other-workspace-1", "eastus2euap"),
            self._account("other-workspace-2", "eastus2euap"),
            self._account("other-workspace-3", "eastus2euap"),
        ] + [
            self._account(self._shard_name(prefix, i), "eastus2euap")
            for i in range(1, 51)
        ]
        result = self._run({"AZ_MONITOR_ACCOUNTS_JSON": json.dumps(accounts)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("existing regional Microsoft.Monitor/accounts=53", result.stdout)
        self.assertIn("missing_workspaces=0", result.stdout)
        self.assertIn("projected_total=53", result.stdout)

    def test_partial_missing_quota_math(self):
        """Only some of the target workspaces already exist -- missing must
        count exactly the remainder, not the full desired count."""
        prefix = self.amw_name_prefix
        accounts = [
            self._account("other-workspace-1", "eastus2euap"),
            self._account("other-workspace-2", "eastus2euap"),
            self._account("other-workspace-3", "eastus2euap"),
        ] + [
            self._account(self._shard_name(prefix, i), "eastus2euap")
            for i in range(1, 41)  # 40 of the 50 target shards already exist
        ]
        result = self._run({"AZ_MONITOR_ACCOUNTS_JSON": json.dumps(accounts)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("existing regional Microsoft.Monitor/accounts=43", result.stdout)
        self.assertIn("missing_workspaces=10", result.stdout)
        self.assertIn("projected_total=53", result.stdout)

    def test_real_quota_overflow_still_blocked(self):
        """Missing-name math must never let a genuine overflow through: if
        the region is already saturated with UNRELATED workspaces, the new
        run's still-missing target names must still trip the limit."""
        accounts = [
            self._account(f"unrelated-{i}", "eastus2euap") for i in range(100)
        ]
        result = self._run({"AZ_MONITOR_ACCOUNTS_JSON": json.dumps(accounts)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("150", result.stderr)
        self.assertIn("AKS_AMW_REGIONAL_WORKSPACE_LIMIT (100)", result.stderr)

    def test_quota_counts_only_matching_region(self):
        """Accounts in a different region must not count toward this
        region's projected total."""
        result = self._run({
            "REGION": "westus2",
            "AKS_AMW_REGIONAL_WORKSPACE_LIMIT": "51",
        })
        # Only the single westus2 account in the fixture counts; 50 desired,
        # none match a westus2 target name -> 1 existing + 50 missing = 51.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("existing regional Microsoft.Monitor/accounts=1", result.stdout)
        self.assertIn("missing_workspaces=50", result.stdout)

    def test_ceil_division_rounds_up_partial_shard(self):
        # 101 clusters / 2 per workspace -> ceil = 51, not 50 (floor).
        result = self._run({"CLUSTER_COUNT": "101"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("desired_workspaces=51", result.stdout)

    def test_clusters_per_workspace_one_uses_mesh_naming(self):
        """cpw=1 targets must use "<prefix>-mesh-<i>" naming (cluster roles
        are mesh-1..mesh-N), not shard-NNN."""
        prefix = self.amw_name_prefix
        accounts = [
            self._account(self._mesh_name(prefix, 1), "eastus2euap"),
            self._account(self._mesh_name(prefix, 2), "eastus2euap"),
        ]
        result = self._run({
            "AKS_AMW_CLUSTERS_PER_WORKSPACE": "1",
            "CLUSTER_COUNT": "3",
            "AZ_MONITOR_ACCOUNTS_JSON": json.dumps(accounts),
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("desired_workspaces=3", result.stdout)
        # mesh-1 and mesh-2 already exist; only mesh-3 is missing.
        self.assertIn("missing_workspaces=1", result.stdout)


class TestRegionalWorkspaceQuotaRotationEnabled(ManagedTelemetryPreflightTestCase):
    """Rotation-enabled (n=2-style) conservative path: the generation
    (base prefix vs a bounded -rN ring slot) is only chosen later at
    configure time, so this preflight cannot compute exact target names and
    must keep assuming every desired workspace is newly created -- even if
    workspaces with those exact names already happen to exist."""

    def test_conservative_upper_bound_ignores_existing_name_matches(self):
        prefix = "cmsh-scale-eastus2euap-amw"
        accounts = [
            # Both target names for this n=2-shaped run already exist, but
            # rotation-enabled must NOT treat them as "not missing".
            self._account(self._mesh_name(prefix, 1), "eastus2euap"),
            self._account(self._mesh_name(prefix, 2), "eastus2euap"),
        ]
        result = self._run({
            "AKS_AMW_ROTATION_ENABLED": "true",
            "AKS_CONTROL_PLANE_AMW_NAME_PREFIX": prefix,
            "CLUSTER_COUNT": "2",
            "AKS_AMW_CLUSTERS_PER_WORKSPACE": "1",
            "AZ_MONITOR_ACCOUNTS_JSON": json.dumps(accounts),
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rotation_enabled=true", result.stdout)
        self.assertIn("desired_workspaces=2", result.stdout)
        # Conservative: missing == desired, NOT 0, even though both target
        # names already exist.
        self.assertIn("missing_workspaces=2", result.stdout)
        self.assertIn("existing regional Microsoft.Monitor/accounts=2", result.stdout)
        self.assertIn("projected_total=4", result.stdout)

    def test_conservative_path_still_blocks_when_over_limit(self):
        result = self._run({
            "AKS_AMW_ROTATION_ENABLED": "true",
            "CLUSTER_COUNT": "100",
            "AKS_AMW_CLUSTERS_PER_WORKSPACE": "2",
            "AKS_AMW_REGIONAL_WORKSPACE_LIMIT": "52",
        })
        # 50 desired (conservatively all "missing") + 3 existing = 53 > 52.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("53", result.stderr)
        self.assertIn("AKS_AMW_REGIONAL_WORKSPACE_LIMIT (52)", result.stderr)


class TestNumericInputValidation(ManagedTelemetryPreflightTestCase):
    def test_non_numeric_cluster_count_fails_clearly(self):
        result = self._run({"CLUSTER_COUNT": "abc"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLUSTER_COUNT must be a positive integer", result.stderr)

    def test_zero_cluster_count_fails(self):
        result = self._run({"CLUSTER_COUNT": "0"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLUSTER_COUNT must be a positive integer", result.stderr)

    def test_negative_clusters_per_workspace_fails(self):
        result = self._run({"AKS_AMW_CLUSTERS_PER_WORKSPACE": "-1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AKS_AMW_CLUSTERS_PER_WORKSPACE must be a positive integer", result.stderr)

    def test_non_numeric_regional_workspace_limit_fails(self):
        result = self._run({"AKS_AMW_REGIONAL_WORKSPACE_LIMIT": "many"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AKS_AMW_REGIONAL_WORKSPACE_LIMIT must be a positive integer", result.stderr)

    def test_non_numeric_max_active_time_series_fails(self):
        result = self._run({"AKS_AMW_MAX_ACTIVE_TIME_SERIES": "2e6"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AKS_AMW_MAX_ACTIVE_TIME_SERIES must be a positive integer", result.stderr)

    def test_non_numeric_max_events_per_minute_fails(self):
        result = self._run({"AKS_AMW_MAX_EVENTS_PER_MINUTE": "unset"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AKS_AMW_MAX_EVENTS_PER_MINUTE must be a positive integer", result.stderr)

    def test_missing_cluster_count_fails(self):
        env = os.environ.copy()
        env["PATH"] = self.bin_dir + os.pathsep + env["PATH"]
        env["AZ_CALL_LOG"] = self.call_log
        env["AZURE_SUBSCRIPTION_ID"] = "11111111-1111-1111-1111-111111111111"
        env["AZ_ACCOUNT_ID"] = "11111111-1111-1111-1111-111111111111"
        env["REGION"] = "eastus2euap"
        env.pop("CLUSTER_COUNT", None)
        result = subprocess.run(
            ["bash", "-c", self.script],
            capture_output=True, text=True, env=env, check=False, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLUSTER_COUNT is required", result.stderr)

    def test_validation_runs_before_any_az_call(self):
        """Malformed numeric input must fail before any network/az call, so
        a typo in a pipeline variable doesn't waste an Azure round-trip."""
        result = self._run({"CLUSTER_COUNT": "not-a-number"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._calls(), [])


if __name__ == "__main__":
    unittest.main()
