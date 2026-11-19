"""Opt-in AKS CRI driver for disposable test clusters.

Creates temporary cluster-wide RBAC, matching the v2 CL2 example. This is NOT a
least-privilege role: CL2 installs Prometheus/CRDs/RBAC and creates namespaces.
Do not enable on shared clusters without explicit approval.
"""
import json
from pathlib import Path
import shlex
import subprocess
import time
import uuid

from utils.logger_config import get_logger

logger = get_logger(__name__)
ROOT = "/root/perf-tests/clusterloader2"
REPORTS = ROOT + "/results"
STATUS = ROOT + "/exit-code"
ACK = ROOT + "/reports-collected"


def build_resources(name, image, config_dir, scrape_kubelets, scrape_containerd, timeout):
    directory = Path(config_dir)
    if any(path.is_dir() for path in directory.iterdir()):
        raise ValueError("The CRI runner expects a flat config directory")
    data = {path.name: path.read_text(encoding="utf-8")
            for path in directory.iterdir() if path.is_file()}
    if not {"config.yaml", "overrides.yaml", "deployment_template.yaml",
            "kubelet-measurement.yaml", "containerd-measurements.yaml"} <= data.keys():
        raise ValueError("Missing CRI configuration or generated overrides.yaml")
    if sum(len(key.encode()) + len(value.encode()) for key, value in data.items()) > 1024 * 1024:
        raise ValueError("CRI config exceeds the ConfigMap 1 MiB limit")

    args = [
        "--provider=aks", "--v=2", "--enable-exec-service=False",
        "--enable-prometheus-server=True",
        f"--prometheus-scrape-kubelets={scrape_kubelets}",
        "--run-from-cluster=true", "--testconfig", ROOT + "/config/config.yaml",
        "--report-dir", REPORTS, "--tear-down-prometheus-server=False",
        "--prometheus-scrape-kube-state-metrics=False",
        "--prometheus-scrape-metrics-server=False",
    ]
    if scrape_containerd:
        args.append(f"--prometheus-scrape-containerd={scrape_containerd}")
    args.append("--testoverrides=" + ROOT + "/config/overrides.yaml")
    # kubectl cp needs a running container. Keep it alive until collection is ACKed.
    script = (
        shlex.join(["./clusterloader2"] + args) + "\n"
        "rc=$?\n"
        f'printf "%s" "$rc" > {STATUS}\n'
        f'for i in $(seq 1 300); do test -f {ACK} && exit "$rc"; sleep 2; done\n'
        'echo "Report collection timed out" >&2\nexit 124\n'
    )
    metadata = {"name": name, "namespace": name}
    return [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name}},
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": metadata,
         "automountServiceAccountToken": True},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
         "metadata": {"name": name},
         "rules": [{"apiGroups": ["*"], "resources": ["*"], "verbs": ["*"]}]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
         "metadata": {"name": name},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io",
                     "kind": "ClusterRole", "name": name},
         "subjects": [{"kind": "ServiceAccount", "name": name, "namespace": name}]},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": metadata, "data": data},
        {"apiVersion": "batch/v1", "kind": "Job", "metadata": metadata,
         "spec": {
             "backoffLimit": 0, "activeDeadlineSeconds": timeout + 600,
             "template": {"spec": {
                 "serviceAccountName": name, "automountServiceAccountToken": True,
                 "restartPolicy": "Never",
                 "nodeSelector": {"agentpool": "default", "kubernetes.io/os": "linux"},
                 "tolerations": [{"key": "CriticalAddonsOnly", "operator": "Exists",
                                  "effect": "NoSchedule"}],
                 "containers": [{
                     "name": "cl2", "image": image, "workingDir": ROOT,
                     "command": ["/bin/sh", "-c"], "args": [script],
                     "resources": {"requests": {"cpu": "1", "memory": "2Gi"}},
                     "volumeMounts": [
                         {"name": "config", "mountPath": ROOT + "/config", "readOnly": True},
                         {"name": "results", "mountPath": REPORTS},
                     ],
                 }],
                 "volumes": [
                     {"name": "config", "configMap": {"name": name}},
                     {"name": "results", "emptyDir": {}},
                 ],
             }},
         }},
    ]


def run_in_cluster(kubeconfig, image, config_dir, report_dir,
                   scrape_kubelets, scrape_containerd, timeout=3600):
    name = "cl2-cri-" + uuid.uuid4().hex[:12]
    resources = build_resources(name, image, config_dir, scrape_kubelets,
                                scrape_containerd, timeout)
    reports = Path(report_dir)
    if reports.exists() and any(reports.iterdir()):
        raise ValueError("CL2 report directory must be empty to avoid stale results")
    reports.mkdir(parents=True, exist_ok=True)

    def kubectl(args, check=True, text=True, **kwargs):
        return subprocess.run(
            ["kubectl", "--kubeconfig", kubeconfig, "--request-timeout=30s",
             "-n", name] + args, check=check, capture_output=True, text=text,
            timeout=120, **kwargs)

    created = []
    pod = None
    logger.warning("Opt-in CRI driver %s grants temporary cluster-wide RBAC; "
                   "use only an approved disposable test cluster", name)
    try:
        for resource in resources:
            kubectl(["create", "-f", "-"], input=json.dumps(resource))
            created.append(resource)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pods = json.loads(kubectl(
                ["get", "pods", "-l", "job-name=" + name, "-o", "json"]).stdout)["items"]
            if pods:
                pod = pods[0]["metadata"]["name"]
                phase = pods[0].get("status", {}).get("phase")
                if phase in ("Failed", "Succeeded"):
                    raise RuntimeError("CL2 pod terminated before report collection")
                if phase == "Running":
                    status = kubectl(["exec", pod, "--", "cat", STATUS], check=False)
                    if status.returncode == 0:
                        exit_code = int(status.stdout)
                        kubectl(["cp", name + "/" + pod + ":" + REPORTS + "/.", str(reports)])
                        kubectl(["exec", pod, "--", "touch", ACK])
                        if exit_code:
                            raise subprocess.CalledProcessError(exit_code, ["clusterloader2"])
                        if not (reports / "junit.xml").is_file():
                            raise RuntimeError("CL2 produced no junit.xml")
                        return
            time.sleep(5)
        raise TimeoutError(f"CL2 job {name} timed out after {timeout}s")
    finally:
        # Preserve diagnostics before deleting the driver, including on CL2/copy failure.
        if pod:
            try:
                logs = kubectl(["logs", pod], check=False, text=False)
                (reports / "cl2-driver.log").write_bytes(logs.stdout + logs.stderr)
            except (OSError, subprocess.SubprocessError) as error:
                logger.warning("Could not save CL2 driver logs: %s", error)
        cleanup_failed = []
        for resource in reversed(created):
            try:
                result = kubectl(
                    ["delete", resource["kind"], name, "--ignore-not-found", "--wait=false"],
                    check=False)
                if result.returncode:
                    cleanup_failed.append(resource["kind"])
            except (OSError, subprocess.SubprocessError):
                cleanup_failed.append(resource["kind"])
        if cleanup_failed:
            logger.error("Cleanup required for %s: %s", name, cleanup_failed)
            raise RuntimeError(f"CL2 cleanup failed for {name}: {cleanup_failed}")
