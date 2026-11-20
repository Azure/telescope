import base64
from functools import partial
import json
from pathlib import Path
import subprocess
import time
import uuid


def _kubectl(kubeconfig, namespace, *args, check=True, stdout=subprocess.PIPE, stdin=None):
    # A command can span multiple 30s API requests (e.g. wait for 90s or copy reports).
    result = subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "--request-timeout=30s", "-n", namespace, *args],
        input=stdin, stdout=stdout, stderr=subprocess.PIPE, timeout=120, check=False,
    )
    if check and result.returncode:
        raise RuntimeError(f"kubectl {' '.join(args)}: {result.stderr.decode(errors='replace')}")
    return result


def run_cl2_job(kubeconfig, image, config_dir, report_dir, arguments):
    """Keep reports available until copied; publish-results returns the saved exit status."""
    report_dir = Path(report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    name = f"cl2-driver-{uuid.uuid4().hex[:12]}"
    status_file = report_dir / f"{name}.exit-code"
    status_file.write_text("1", encoding="ascii")
    exit_code, pod, created = 1, None, False

    kubectl = partial(_kubectl, kubeconfig, name)
    config_maps, sources = [], []
    for path in sorted(Path(config_dir).rglob("*")):
        if path.is_file():
            content = path.read_bytes()
            if len(content) > 1048576:
                raise ValueError(f"CL2 config file exceeds the ConfigMap 1 MiB limit: {path}")
            config_name = f"{name}-config-{len(config_maps)}"
            config_maps.append({
                "apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": config_name},
                "binaryData": {"config": base64.b64encode(content).decode("ascii")},
            })
            sources.append({"configMap": {"name": config_name, "items": [
                {"key": "config", "path": path.relative_to(config_dir).as_posix()},
            ]}})
    if not config_maps:
        raise ValueError("CL2 configuration must be nonempty")

    timeout = 86400
    root = "/root/perf-tests/clusterloader2"
    resources = [
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": name}},
        # CL2 installs CRDs and Prometheus RBAC across this disposable test cluster.
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
         "metadata": {"name": name}, "rules": [
             {"apiGroups": ["*"], "resources": ["*"], "verbs": ["*"]},
             {"nonResourceURLs": ["/metrics"], "verbs": ["get"]},
         ]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
         "metadata": {"name": name},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": name},
         "subjects": [{"kind": "ServiceAccount", "name": name, "namespace": name}]},
        *config_maps,
        {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name}, "spec": {
            "backoffLimit": 0, "activeDeadlineSeconds": timeout + 600,
            "template": {"spec": {
                "serviceAccountName": name, "restartPolicy": "Never",
                "nodeSelector": {"kubernetes.io/os": "linux"},
                "containers": [{
                    "name": "cl2", "image": image,
                    "command": ["/bin/sh", "-c"],
                    "args": ['''./clusterloader2 "$@"
rc=$?
printf '%s\\n' "$rc" > /cl2-control/exit-code.tmp
mv /cl2-control/exit-code.tmp /cl2-control/exit-code || exit 1
for i in $(seq 1 300); do
  test -f /cl2-control/reports-collected && exit "$rc"
  sleep 2
done
echo "Report collection timed out" >&2
exit 124
''', "cl2", *arguments],
                    "resources": {"requests": {
                        "cpu": "1",
                        "memory": "2Gi",
                    }},
                    "volumeMounts": [
                        {"name": "config", "mountPath": f"{root}/config", "readOnly": True},
                        {"name": "reports", "mountPath": f"{root}/results"},
                        {"name": "control", "mountPath": "/cl2-control"},
                    ],
                }],
                "volumes": [
                    {"name": "config", "projected": {"sources": sources}},
                    {"name": "reports", "emptyDir": {}}, {"name": "control", "emptyDir": {}},
                ],
            }},
        }},
    ]
    try:
        kubectl("create", "namespace", name)
        created = True
        kubectl("create", "-f", "-", stdin=json.dumps(
            {"apiVersion": "v1", "kind": "List", "items": resources}).encode())
        deadline = time.monotonic() + timeout
        startup_deadline = time.monotonic() + 300
        started = False
        while time.monotonic() < deadline:
            pods = json.loads(kubectl("get", "pods", "-l", f"job-name={name}", "-o", "json").stdout)["items"]
            if pods:
                pod = pods[0]["metadata"]["name"]
                phase = pods[0].get("status", {}).get("phase")
                if phase in ("Failed", "Succeeded"):
                    raise RuntimeError(f"CL2 Pod {pod} terminated before report collection")
                if phase == "Pending":
                    kubectl("wait", "--for=condition=PodScheduled", f"pod/{pod}", "--timeout=90s")
                if phase == "Running":
                    started = True
                    result = kubectl("exec", pod, "--", "cat", "/cl2-control/exit-code", check=False)
                    if result.returncode:
                        time.sleep(5)
                        continue
                    code = int(result.stdout)
                    if not 0 <= code <= 255:
                        raise ValueError(f"Invalid CL2 exit code: {code}")
                    kubectl("cp", f"{pod}:{root}/results/.", str(report_dir))
                    if code == 0:
                        kubectl("exec", pod, "--", "test", "-s", f"{root}/results/junit.xml")
                    kubectl("exec", pod, "--", "touch", "/cl2-control/reports-collected")
                    kubectl("wait", f"--for=jsonpath={{.status.containerStatuses[0].state.terminated.exitCode}}={code}",
                            f"pod/{pod}", "--timeout=60s")
                    exit_code = code
                    break
            elif pod:
                raise RuntimeError(f"CL2 Pod {pod} disappeared before report collection")
            if not started and time.monotonic() >= startup_deadline:
                raise TimeoutError("CL2 Pod did not start within five minutes")
            time.sleep(5)
        else:
            exit_code = 124
            raise TimeoutError("CL2 Job timed out")
    finally:
        if pod:
            try:
                with (report_dir / f"{name}.log").open("wb") as output:
                    result = kubectl("logs", pod, stdout=output, check=False)
                if result.returncode:
                    print(f"Warning: CL2 log collection failed: {result.stderr.decode(errors='replace')}")
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f"Warning: CL2 log collection failed: {error}")
        if created:
            try:
                kubectl("delete", "namespace,clusterrole,clusterrolebinding", name,
                        "--ignore-not-found", "--wait=false")
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                print(f"CL2 cleanup failed; cluster teardown is required: {error}")
                exit_code = exit_code or 1
        status_file.write_text(str(exit_code), encoding="ascii")
    print(f"CL2 Job exited {exit_code}; reports and status saved to {report_dir}")
    return exit_code
