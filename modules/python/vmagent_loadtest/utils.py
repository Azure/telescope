"""Subprocess helpers, template rendering, port-forwarding, and HTTP retry."""

import functools
import subprocess
import time
from http.client import RemoteDisconnected
from pathlib import Path

import requests

from .config import log


def retry(max_attempts: int = 3, backoff: float = 10.0,
          exceptions: tuple = (RuntimeError,)):
    """Decorator that retries a function on specified exceptions with exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        raise
                    delay = backoff * (2 ** (attempt - 1))
                    log.warning("%s failed (attempt %d/%d): %s — retrying in %.0fs",
                                func.__name__, attempt, max_attempts, e, delay)
                    time.sleep(delay)
        return wrapper
    return decorator


def run(cmd: list[str], *, check: bool = True, capture: bool = True,
        input: str | None = None) -> subprocess.CompletedProcess:
    """Run a command, log it, and return the result."""
    log.debug("$ %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        input=input,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise RuntimeError(f"Command failed (rc={result.returncode}): {' '.join(cmd)}\n{stderr}")
    return result


def kubectl(kubeconfig: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(["kubectl", "--kubeconfig", kubeconfig, *args], check=check)


def render_template(manifest_path: Path, replacements: dict[str, str]) -> str:
    content = manifest_path.read_text()
    for key, val in replacements.items():
        content = content.replace(key, str(val))
    return content


def kubectl_apply(kubeconfig: str, manifest_text: str) -> None:
    run(["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"],
        input=manifest_text, capture=False)


class PortForward:
    """Context manager that opens a kubectl port-forward and cleans up on exit."""

    def __init__(self, kubeconfig: str, namespace: str, resource: str,
                 remote_port: int, local_port: int):
        self.cmd = [
            "kubectl", "--kubeconfig", kubeconfig, "-n", namespace,
            "port-forward", resource, f"{local_port}:{remote_port}",
        ]
        self.local_port = local_port
        self.proc = None

    def __enter__(self):
        self.proc = subprocess.Popen(
            self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        # Wait for port-forward to establish, verifying the process is alive
        time.sleep(3)
        if self.proc.poll() is not None:
            _, stderr = self.proc.communicate()
            raise RuntimeError(
                f"port-forward exited immediately (rc={self.proc.returncode}): "
                f"{stderr.decode(errors='replace').strip()}"
            )
        return self

    def __exit__(self, *exc):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return False

    @property
    def url(self) -> str:
        return f"http://localhost:{self.local_port}"


def retry_request(url: str, retries: int = 3, backoff: float = 3.0,
                  timeout: int = 10, **kwargs) -> requests.Response:
    """GET with retries for transient connection errors (RemoteDisconnected, etc)."""
    for attempt in range(1, retries + 1):
        try:
            # Port-forward calls must bypass proxy env vars; otherwise localhost
            # requests may be sent to an HTTP proxy and fail with connection refused.
            with requests.Session() as session:
                session.trust_env = False
                resp = session.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, RemoteDisconnected) as e:
            if attempt == retries:
                raise
            log.warning("Request to %s failed (attempt %d/%d): %s — retrying in %.0fs",
                        url, attempt, retries, e, backoff)
            time.sleep(backoff)
