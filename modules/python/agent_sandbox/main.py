"""Agent Sandbox claim throughput benchmark.

    configure  installs KWOK (simulated nodes), the agent-sandbox controller and the warm pools, and waits until
               the pools are full
    execute    runs the in-cluster load generator through a ladder of claim rates and copies its results back
    collect    writes one JSON line per rate to the results file

The generator (generator.py) runs in a pod from a public Python image; this module drives it with kubectl.
"""

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

import yaml

from agent_sandbox import manifests as mf
from agent_sandbox import metrics

FIELD_MANAGER = "agent-sandbox-benchmark"
HERE = os.path.dirname(os.path.abspath(__file__))


def log(message):
    print(f"{datetime.now(timezone.utc):%H:%M:%S} {message}", flush=True)


def kubectl(args, stdin=None, timeout=600, binary=False):
    proc = subprocess.run(["kubectl"] + args, input=stdin, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args[:3])}: {proc.stderr.decode(errors='replace')[-2000:]}")
    return proc.stdout if binary else proc.stdout.decode()


def apply(docs):
    body = json.dumps({"apiVersion": "v1", "kind": "List", "items": docs}).encode()
    kubectl(["apply", "--server-side", "--force-conflicts", "--field-manager=" + FIELD_MANAGER, "-f", "-"], stdin=body)


def apply_release(docs):
    """Applies a release: its CustomResourceDefinitions first, once they are established everything else."""
    crds = [d for d in docs if d.get("kind") == "CustomResourceDefinition"]
    if crds:
        apply(crds)
        for crd in crds:
            kubectl(["wait", "--for=condition=Established", "crd/" + crd["metadata"]["name"], "--timeout=300s"],
                    timeout=330)
    apply([d for d in docs if d.get("kind") != "CustomResourceDefinition"])


def wait_for(description, check, timeout, interval=10):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            ok, last = check()
            if ok:
                return last
        except RuntimeError as e:  # transient API errors while waiting
            last = str(e)[-300:]
        time.sleep(interval)
    raise TimeoutError(f"{description}: not done after {timeout} s (last: {last})")


def fetch(url, sha256, workdir):
    """Downloads a pinned release file once, checks its SHA-256 and returns its documents."""
    path = os.path.join(workdir, os.path.basename(url))
    if not os.path.exists(path):
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = resp.read()
        with open(path, "wb") as f:
            f.write(data)
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        raise ValueError(f"{url}: sha256 {digest}, want {sha256}")
    with open(path, encoding="utf-8") as f:
        return [d for d in yaml.safe_load_all(f) if d]


def selector(text):
    """key=value[,key=value] as a dict."""
    return dict(kv.split("=", 1) for kv in text.split(",") if kv)


def count_ready_nodes(label):
    items = json.loads(kubectl(["get", "nodes", "-l", label, "-o", "json"]))["items"]
    return sum(1 for n in items for c in n.get("status", {}).get("conditions", [])
               if c["type"] == "Ready" and c["status"] == "True")


def count_ready_sandboxes():
    items = json.loads(kubectl(["get", "sandboxwarmpools", "-A", "-o", "json"]))["items"]
    return sum(p.get("status", {}).get("readyReplicas", 0) for p in items)


def configure(args):
    os.makedirs(args.workdir, exist_ok=True)
    node_selector = selector(args.node_selector)
    log(f"KWOK {mf.KWOK_VERSION} on {node_selector}")
    apply_release(mf.kwok_docs(fetch(mf.KWOK_URL, mf.KWOK_SHA256, args.workdir), node_selector))
    apply(fetch(mf.KWOK_STAGE_URL, mf.KWOK_STAGE_SHA256, args.workdir))
    kubectl(["-n", "kube-system", "rollout", "status", "deployment/kwok-controller", "--timeout=600s"], timeout=660)
    log(f"{args.kwok_nodes} simulated nodes with {args.pods_per_node} pods each")
    apply(mf.kwok_nodes(args.kwok_nodes, args.pods_per_node))
    label = mf.KWOK_NODE_LABEL + "=true"
    wait_for("KWOK nodes Ready", lambda: (count_ready_nodes(label) >= args.kwok_nodes, None), 600)

    log(f"agent-sandbox {mf.AGENT_SANDBOX_VERSION}, controller CPU limit {args.controller_cpu}")
    docs = mf.controller_docs(fetch(mf.AGENT_SANDBOX_URL, mf.AGENT_SANDBOX_SHA256, args.workdir), node_selector,
                              cpu_limit=args.controller_cpu)
    apply_release(docs)
    namespace = [d for d in docs if d.get("kind") == "Deployment"][0]["metadata"]["namespace"]
    kubectl(["-n", namespace, "rollout", "status", "deployment/" + mf.CONTROLLER_NAME, "--timeout=600s"], timeout=660)

    # AKS provides the template's runtime class; elsewhere the pods need one to be admitted. KWOK never runs them.
    runtime_class = mf.sandbox_template()["spec"]["podTemplate"]["spec"]["runtimeClassName"]
    try:
        kubectl(["get", "runtimeclass", runtime_class])
    except RuntimeError:
        apply([{"apiVersion": "node.k8s.io/v1", "kind": "RuntimeClass", "metadata": {"name": runtime_class},
                "handler": "kata"}])

    want = args.pools * args.replicas_per_pool
    log(f"{args.pools} warm pools of {args.replicas_per_pool} Sandboxes")
    apply(mf.pool_docs(args.pools, args.replicas_per_pool))
    wait_for("warm pools Ready", lambda: (count_ready_sandboxes() >= want, None), args.pool_timeout, interval=15)
    log("configured")


def generator_exec(script, binary=False, timeout=600):
    return kubectl(["-n", mf.GENERATOR_NAMESPACE, "exec", mf.GENERATOR_NAME, "--", "python3", "-c", script],
                   timeout=timeout, binary=binary)


def generator_done():
    phase = kubectl(["-n", mf.GENERATOR_NAMESPACE, "get", "pod", mf.GENERATOR_NAME, "-o", "jsonpath={.status.phase}"])
    if phase in ("Failed", "Succeeded"):
        logs = kubectl(["-n", mf.GENERATOR_NAMESPACE, "logs", mf.GENERATOR_NAME, "--tail=50"])
        raise SystemExit(f"generator pod {phase} before writing its results:\n{logs}")
    return generator_exec("import os;print(os.path.exists('/results/DONE'))").strip() == "True", phase


def execute(args):
    os.makedirs(args.workdir, exist_ok=True)
    rates = [float(r) for r in args.rates.split(",")]
    plan = mf.plan(args.run_id, args.pools, rates, args.duration, args.warmup, args.dwell)
    with open(os.path.join(HERE, "generator.py"), encoding="utf-8") as f:
        source = f.read()
    kubectl(["-n", mf.GENERATOR_NAMESPACE, "delete", "pod", mf.GENERATOR_NAME, "--ignore-not-found", "--wait=true"])
    apply(mf.generator_docs(plan, source, selector(args.node_selector)))
    kubectl(["-n", mf.GENERATOR_NAMESPACE, "wait", "--for=condition=Ready", "pod/" + mf.GENERATOR_NAME,
             "--timeout=600s"], timeout=660)
    log(f"generator running: rates {args.rates}/s, {args.duration} s each after {args.warmup} s of warmup")
    # per rate: the warmup and the measured time, plus up to 5 minutes of drain and 15 of warm pool refill
    wait_for("generator finished", generator_done, len(rates) * (args.duration + args.warmup + 1200) + 600,
             interval=30)
    for name in ("claims.jsonl.gz", "run.json"):
        data = generator_exec(f"import sys;sys.stdout.buffer.write(open('/results/{name}','rb').read())", binary=True)
        with open(os.path.join(args.workdir, name), "wb") as f:
            f.write(data)
    generator_exec("open('/results/COLLECTED','w').close()")
    log(kubectl(["-n", mf.GENERATOR_NAMESPACE, "logs", mf.GENERATOR_NAME, "--tail=20"]))


def collect(args):
    with open(os.path.join(args.workdir, "run.json"), encoding="utf-8") as f:
        run = json.load(f)
    with gzip.open(os.path.join(args.workdir, "claims.jsonl.gz"), "rt", encoding="utf-8") as f:
        claims = [json.loads(line) for line in f]
    configuration = {"agent_sandbox_version": mf.AGENT_SANDBOX_VERSION, "kwok_version": mf.KWOK_VERSION,
                     "controller_args": mf.CONTROLLER_ARGS, "pools": len(run["plan"]["pools"]),
                     "plan": {k: v for k, v in run["plan"].items() if k not in ("pools", "phases")}}
    with open(args.result_file, "a", encoding="utf-8") as f:
        for result in metrics.phase_results(run, claims):
            row = {"timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "test_type": "agent-sandbox", "phase": result["phase"], "rate": result["rate"],
                   "duration_seconds": result["durationSeconds"] - result["warmupSeconds"],
                   "verdict": result["verdict"], "verdict_p90": result["verdictP90"], "reasons": result["reasons"],
                   "undrained": result["undrained"], "metrics": result["metrics"], "configuration": configuration,
                   "generator_started_at": run["startedAt"], "cloud_info": args.cloud_info, "run_id": args.run_id,
                   "run_url": args.run_url}
            f.write(json.dumps(row) + "\n")
            log(f"{result['phase']}: {result['verdict']} (p90 {result['verdictP90']}) {'; '.join(result['reasons'])}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("configure")
    p.add_argument("--workdir", required=True)
    p.add_argument("--node_selector", required=True, help="where the controller, KWOK and the generator run")
    p.add_argument("--pools", type=int, default=4)
    p.add_argument("--replicas_per_pool", type=int, default=750)
    p.add_argument("--kwok_nodes", type=int, default=24)
    p.add_argument("--pods_per_node", type=int, default=1000)
    p.add_argument("--controller_cpu", default="12")
    p.add_argument("--pool_timeout", type=int, default=3600)
    p = sub.add_parser("execute")
    p.add_argument("--workdir", required=True)
    p.add_argument("--node_selector", required=True)
    p.add_argument("--run_id", required=True)
    p.add_argument("--pools", type=int, default=4)
    p.add_argument("--rates", default="50,100,150,200,250,300", help="claims per second, comma-separated")
    p.add_argument("--duration", type=int, default=300, help="measured seconds per rate, after the warmup")
    p.add_argument("--warmup", type=int, default=60)
    p.add_argument("--dwell", type=float, default=2.0, help="seconds between a claim being Ready and its delete")
    p = sub.add_parser("collect")
    p.add_argument("--workdir", required=True)
    p.add_argument("--run_id", required=True)
    p.add_argument("--run_url", default="")
    p.add_argument("--cloud_info", default="")
    p.add_argument("--result_file", required=True)
    args = parser.parse_args(argv)
    {"configure": configure, "execute": execute, "collect": collect}[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
