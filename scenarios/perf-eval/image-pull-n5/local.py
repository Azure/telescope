"""Run concurrent layer downloads on one isolated local kind node."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import getpass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

import pull
from download import DownloadError, error_message


CLUSTER = "acr-scaleout-local"
CONTEXT = f"kind-{CLUSTER}"
NODE_IMAGE = "docker.io/kindest/node:v1.34.0"
RUNNER_IMAGE = "docker.io/library/python:3.12.12-slim"
STATE = Path.home() / ".local" / "state" / "telescope-five-pulls"
BATCH_NAMESPACES = (f"{pull.NAMESPACE}-batch-1", f"{pull.NAMESPACE}-batch-2")
BATCH_INTERVAL_SECONDS = 60


def command(*arguments, payload=None, timeout=180):
    completed = subprocess.run(
        arguments, input=json.dumps(payload) if payload is not None else None,
        text=True, capture_output=True, timeout=timeout, check=True,
    )
    if completed.stderr:
        print(completed.stderr.strip(), file=sys.stderr)
    return completed.stdout


@contextmanager
def local_context():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DownloadError("Another local download command is already running") from None
        previous = {key: os.environ.get(key) for key in ("KUBECONFIG", "KIND_EXPERIMENTAL_PROVIDER")}
        os.environ["KUBECONFIG"] = str(STATE / "kubeconfig")
        os.environ["KIND_EXPERIMENTAL_PROVIDER"] = "podman"
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def ensure_node_running(node):
    nodes = command("kind", "get", "nodes", "--name", CLUSTER).splitlines()
    if nodes != [node]:
        raise DownloadError("Refusing to start an unexpected set of local kind containers")
    status = command("podman", "inspect", node, "--format", "{{.State.Status}}").strip()
    if status == "running":
        return
    if status not in ("configured", "created", "exited", "stopped"):
        raise DownloadError(f"Local node {node} is {status!r}; inspect its state before retrying")
    print(f"Starting existing local node {node} (state: {status})", flush=True)
    command("systemd-run", "--scope", "--user", "-p", "Delegate=yes", "podman", "start", node)
    status = command("podman", "inspect", node, "--format", "{{.State.Status}}").strip()
    if status != "running":
        raise DownloadError(f"Local node {node} did not stay running after start (state: {status})")


def wait_for_api():
    deadline = time.monotonic() + 180
    last_error = "API readiness was not observed"
    while time.monotonic() < deadline:
        try:
            response = command("kubectl", "--request-timeout=5s", "get", "--raw=/readyz", timeout=10)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            last_error = error.stderr or str(error)
            if isinstance(last_error, bytes):
                last_error = last_error.decode("utf-8", errors="replace")
            last_error = " ".join(last_error.split())[:512]
        else:
            if response.strip() == "ok":
                return
            last_error = f"Unexpected API readiness response: {response.strip()[:512]}"
        print(f"Waiting for local Kubernetes API: {last_error}", flush=True)
        time.sleep(5)
    raise DownloadError(f"Local Kubernetes API did not become ready within 180s: {last_error}")


def prepare_cluster():
    command("podman", "info", "--format", "{{.Version.Version}}")
    clusters = command("kind", "get", "clusters").splitlines()
    if CLUSTER not in clusters:
        print(f"Creating dedicated local cluster {CLUSTER}", flush=True)
        config = {
            "kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4",
            "nodes": [{"role": "control-plane", "labels": {"cri-resource-consume": "true"}}],
        }
        command(
            "systemd-run", "--scope", "--user", "-p", "Delegate=yes",
            "kind", "create", "cluster", "--name", CLUSTER, "--image", NODE_IMAGE,
            "--config", "-", "--kubeconfig", os.environ["KUBECONFIG"], "--wait", "180s",
            payload=config, timeout=900,
        )
    expected_name = f"{CLUSTER}-control-plane"
    ensure_node_running(expected_name)
    command("kind", "export", "kubeconfig", "--name", CLUSTER, "--kubeconfig", os.environ["KUBECONFIG"])
    Path(os.environ["KUBECONFIG"]).chmod(0o600)
    if command("kubectl", "config", "current-context").strip() != CONTEXT:
        raise DownloadError("Refusing to run against a different Kubernetes context")
    wait_for_api()
    command("kubectl", "--request-timeout=150s", "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=120s")
    nodes = json.loads(command("kubectl", "--request-timeout=30s", "get", "nodes", "-o", "json"))["items"]
    if len(nodes) != 1 or nodes[0]["metadata"]["name"] != expected_name:
        raise DownloadError("The dedicated local cluster must contain exactly its one expected node")
    if nodes[0]["metadata"].get("labels", {}).get("cri-resource-consume") != "true":
        raise DownloadError("Local node is missing the cri-resource-consume=true label")
    if nodes[0].get("spec", {}).get("unschedulable", False):
        raise DownloadError("The local node is cordoned")
    images = command("podman", "images", "--format", "{{.Repository}}:{{.Tag}}").splitlines()
    if RUNNER_IMAGE not in images:
        print("Downloading the Python helper image (not the test layer)", flush=True)
        command("podman", "pull", RUNNER_IMAGE, timeout=300)
    cached = command(
        "podman", "exec", expected_name, "ctr", "--namespace", "k8s.io", "images", "list", "--quiet",
    ).splitlines()
    if RUNNER_IMAGE not in cached:
        # Archive loading does not depend on kind's Docker-specific host image lookup.
        with tempfile.TemporaryDirectory(prefix="telescope-helper-image-") as directory:
            archive = str(Path(directory) / "python.tar")
            command("podman", "save", "--format", "docker-archive", "--output", archive, RUNNER_IMAGE, timeout=300)
            command("kind", "load", "image-archive", archive, "--name", CLUSTER, timeout=300)
    print(f"Ready: {expected_name}; kubeconfig: {os.environ['KUBECONFIG']}", flush=True)
    return expected_name


def check_workers(node, *, pull_count=pull.PULL_COUNT):
    namespace = "acr-five-check-" + uuid.uuid4().hex[:8]
    command("kubectl", "create", "namespace", namespace)
    try:
        command("kubectl", "create", "serviceaccount", pull.SERVICE_ACCOUNT, "-n", namespace)
        command("kubectl", "create", "-f", "-", payload={
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": "acr-download-target", "namespace": namespace},
            "type": "Opaque", "stringData": {"target.json": "{}"},
        })
        command("kubectl", "create", "-f", "-", payload={
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": "acr-download-script", "namespace": namespace},
            "data": {"download.py": Path(__file__).with_name("download.py").read_text(encoding="utf-8")},
        })
        workload = pull.manifests(RUNNER_IMAGE, [node] * pull_count)
        for pod in workload["items"]:
            pod["metadata"]["namespace"] = namespace
        command("kubectl", "create", "-f", "-", payload=workload)
        command(
            "kubectl", "--request-timeout=150s", "wait", "-n", namespace,
            "--for=condition=Ready", "pods", "--all", "--timeout=120s",
        )
        pods = json.loads(command("kubectl", "get", "pods", "-n", namespace, "-o", "json"))["items"]
        if len(pods) != pull_count or any(pod["spec"]["nodeName"] != node for pod in pods):
            raise DownloadError(f"Local setup did not place exactly {pull_count} Pods on the expected node")
        print(f"PASS: {pull_count} downloader Pods are Ready on one local node; no target download was started.")
    finally:
        command("kubectl", "delete", "namespace", namespace, "--wait=true", "--timeout=120s")


def run_two_batches(image, run_id):
    processes = []
    next_launch = time.monotonic()
    try:
        for index, namespace in enumerate(BATCH_NAMESPACES, 1):
            delay = next_launch - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            batch_id = f"{run_id}-batch-{index}"
            result_file = STATE / "results" / f"{batch_id}.json"
            arguments = [
                sys.executable, "-B", str(Path(__file__).with_name("pull.py")),
                "--image", image, "--runner-image", RUNNER_IMAGE,
                "--result-file", str(result_file), "--run-id", batch_id,
                "--run-url", result_file.as_uri(), "--namespace", namespace,
                "--local", "--start-immediately",
            ]
            process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, start_new_session=True)
            processes.append(process)
            if index == 1:
                next_launch = time.monotonic() + BATCH_INTERVAL_SECONDS
            print(
                f"Batch {index}/2 launched at {datetime.now(timezone.utc).isoformat()}: "
                f"five downloads; namespace={namespace}; report={result_file}",
                flush=True,
            )
        # Waiting starts only after both coordinators have launched, so the batches can overlap.
        exit_codes = [process.wait() for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                print(f"Interrupting batch coordinator PID {process.pid}; waiting for cleanup.", file=sys.stderr)
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    print(
                        f"Batch coordinator PID {process.pid} did not stop; terminating it. "
                        "Inspect the batch namespaces before retrying.",
                        file=sys.stderr,
                    )
                    process.kill()
                    process.wait()
    for index, code in enumerate(exit_codes, 1):
        print(f"Batch {index}/2 finished with exit code {code}.", flush=True)
    return 0 if all(code == 0 for code in exit_codes) else 1


def execute(args):
    if args.pull_count not in pull.SUPPORTED_PULL_COUNTS:
        raise DownloadError("Expected four or five downloads")
    if args.two_batches and args.pull_count != pull.PULL_COUNT:
        raise DownloadError("Two-batch mode requires five downloads per batch")
    image = f"{args.registry}/{args.image}"
    pull.parse_image(image)
    with local_context():
        node = prepare_cluster()
        if args.setup_only:
            check_workers(node, pull_count=args.pull_count)
            return 0
        # A stale namespace is never deleted automatically; it may own an unfinished run.
        for namespace in (pull.NAMESPACE, *BATCH_NAMESPACES):
            existing = command("kubectl", "get", "namespace", namespace, "--ignore-not-found", "-o", "name").strip()
            if existing:
                raise DownloadError(f"Namespace {namespace} already exists. Inspect it before deleting or retrying.")
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = os.environ.get("ACR_PULL_PASSWORD", "")
            if not password:
                if not sys.stdin.isatty():
                    raise DownloadError("Use an interactive terminal, ACR_PULL_PASSWORD, or --password-stdin")
                password = getpass.getpass(f"Pull password/token for {args.username} at {args.registry}: ")
        if not password or password.startswith("$("):
            raise DownloadError("A registry pull password/token is required")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        result_file = STATE / "results" / f"{run_id}.json"
        run_args = argparse.Namespace(
            image=image, runner_image=RUNNER_IMAGE, result_file=str(result_file),
            run_id=run_id, run_url=result_file.as_uri(),
        )
        previous = {key: os.environ.get(key) for key in ("ACR_PULL_USERNAME", "ACR_PULL_PASSWORD")}
        os.environ["ACR_PULL_USERNAME"] = args.username
        os.environ["ACR_PULL_PASSWORD"] = password
        if args.two_batches:
            print(f"Starting two batches of five one-GiB layer downloads: {image}", flush=True)
            print("Batch 2 launches 60 seconds after batch 1, without waiting for it to finish.", flush=True)
        else:
            print(f"Starting {args.pull_count} one-GiB layer downloads: {image}", flush=True)
            print(f"Result file: {result_file}", flush=True)
        if args.start_immediately or args.two_batches:
            print("Each Pod starts downloading as soon as it starts; no aligned-window wait.", flush=True)
        else:
            print("The workers wait for a common five-minute window. Do not start another run.", flush=True)
        try:
            if args.two_batches:
                status = run_two_batches(image, run_id)
            else:
                status = pull.run(
                    run_args, node_count=1, region="local", registry_resource_group=None,
                    start_immediately=args.start_immediately, pull_count=args.pull_count,
                )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        for namespace in BATCH_NAMESPACES if args.two_batches else (pull.NAMESPACE,):
            remaining = command("kubectl", "get", "namespace", namespace, "--ignore-not-found", "-o", "name").strip()
            if remaining:
                command("kubectl", "wait", "--for=delete", f"namespace/{namespace}", "--timeout=120s")
        if not args.two_batches:
            print(f"Report saved: {result_file}", flush=True)
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, help="ACR hostname without https://")
    parser.add_argument("--image", required=True, help="Repository@sha256:digest; exactly one one-GiB layer")
    parser.add_argument("--username", required=True)
    parser.add_argument("--setup-only", action="store_true", help="Verify the requested number of Ready Pods without registry traffic")
    parser.add_argument("--password-stdin", action="store_true", help="Read the password from stdin, never an argument")
    parser.add_argument("--start-immediately", action="store_true", help="Publish the target before creating Pods; do not wait for an aligned window")
    parser.add_argument("--two-batches", action="store_true", help="Launch five immediate downloads, then another five after 60 seconds")
    parser.add_argument("--pull-count", type=int, choices=pull.SUPPORTED_PULL_COUNTS, default=pull.PULL_COUNT, help="Downloads per single-batch run (4 or 5; default: 5)")
    args = parser.parse_args()
    try:
        return execute(args)
    except (OSError, ValueError, KeyError, DownloadError, subprocess.SubprocessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(f"LOCAL SETUP FAILED: {error}; {error.stderr or ''}", file=sys.stderr)
        else:
            print(f"LOCAL DOWNLOAD FAILED: {error_message(error)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Local run interrupted. Check its report and namespace before retrying.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
