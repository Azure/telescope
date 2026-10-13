"""Generate v1 reference outputs for the node startup parity tests.

Runs the v1 benchmark code (modules/python/clients/kubernetes_client.py on the
`carlota-cilium-testing` branch) on tests/node_startup/scenarios.py and writes
its outputs to v1_golden.json. Re-run only if the scenarios change:

    cd modules/python
    PYTHONPATH=. python3 tests/node_startup/fixtures/generate_v1_golden.py
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
from datetime import datetime as real_datetime
from unittest import mock

from tests.node_startup import scenarios
from tests.node_startup.fake_kubernetes import FakeCoreV1Api, FakeWatch, kubernetes_client, to_model

V1_FILE = "modules/python/clients/kubernetes_client.py"
OUTPUT = os.path.join(os.path.dirname(__file__), "v1_golden.json")


def load_v1_client(ref):
    commit = subprocess.check_output(["git", "rev-parse", ref], text=True).strip()
    source = subprocess.check_output(["git", "show", f"{commit}:{V1_FILE}"], text=True)
    path = os.path.join(tempfile.mkdtemp(), "v1_kubernetes_client.py")
    with open(path, "w", encoding="utf-8") as file:
        file.write(source)
    spec = importlib.util.spec_from_file_location("v1_kubernetes_client", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.KubernetesClient, commit


def fixed_clock_datetime_module(instants):
    """A stand-in `datetime` module whose datetime.now() returns `instants` in order.

    v1 imports `from datetime import datetime, timezone` inside the watch function,
    so swapping sys.modules["datetime"] controls its wall clock.
    """
    queue = list(instants)

    class ClockDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return queue.pop(0)

    module = types.ModuleType("datetime")
    module.__dict__.update(sys.modules["datetime"].__dict__)
    module.datetime = ClockDatetime
    return module


def empty_events_v1(*_args, **_kwargs):
    return mock.Mock(list_namespaced_event=mock.Mock(return_value=mock.Mock(items=[])))


def generate(v1_class):
    v1 = kubernetes_client(v1_class, FakeCoreV1Api())
    golden = {
        "latency": {name: v1._compute_autoscale_latencies(ts) for name, ts in scenarios.LATENCY_SCENARIOS.items()},
        "cilium_metrics": {name: v1._parse_cilium_metrics(text)
                           for name, text in scenarios.CILIUM_METRICS_SCENARIOS.items()},
        "cni_pod": {},
        "watch": {},
        "trigger": {},
    }

    for name, case in scenarios.CNI_POD_SCENARIOS.items():
        k8s = kubernetes_client(v1_class, FakeCoreV1Api(pods=case["pods"], events=case["events"], logs=case["logs"]))
        golden["cni_pod"][name] = k8s.collect_cni_pod_timestamps(
            [scenarios.NODE], scenarios.CILIUM_LABEL)[scenarios.NODE]

    for name, case in scenarios.WATCH_SCENARIOS.items():
        nodes = [to_model(node, "V1Node") for node in case["nodes"]]
        instants = [scenarios.clock(*instant) for instant in case["clock"]]
        with mock.patch("kubernetes.watch.Watch", return_value=FakeWatch(nodes)), \
                mock.patch.dict(sys.modules, {"datetime": fixed_clock_datetime_module(instants)}):
            golden["watch"][name] = v1._watch_node_transitions(
                existing_nodes={scenarios.EXISTING_NODE}, node_pool_name="userpool",
                cni_blocking_taint=case["cni_blocking_taint"])

    for name, events in scenarios.TRIGGER_SCENARIOS.items():
        k8s = kubernetes_client(v1_class, FakeCoreV1Api(events=events))
        with mock.patch("kubernetes.client.EventsV1Api", side_effect=empty_events_v1):
            golden["trigger"][name] = {
                "triggered_scale_up": k8s._get_triggered_scale_up_timestamp(
                    scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE, max_retries=1),
                "first_scheduling_event": k8s._get_first_scheduling_event_timestamp(
                    scenarios.PROBE_POD, scenarios.PROBE_NAMESPACE),
            }
    return golden


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--v1-ref", default="carlota-cilium-testing", help="Git ref holding the v1 code")
    args = parser.parse_args()
    v1_class, commit = load_v1_client(args.v1_ref)
    output = {"generated_from": {"ref": args.v1_ref, "commit": commit, "file": V1_FILE}, **generate(v1_class)}
    with open(OUTPUT, "w", encoding="utf-8") as file:
        json.dump(output, file, indent=2, sort_keys=True)
        file.write("\n")
    print(f"Wrote {OUTPUT} from {args.v1_ref} ({commit})")


if __name__ == "__main__":
    main()
