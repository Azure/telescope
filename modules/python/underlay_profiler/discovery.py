"""Target discovery and guard rails."""

import time
from dataclasses import dataclass
from urllib.parse import urlparse

from kubernetes import client as k8s_client, config as k8s_config

from vmagent_loadtest.quantity import parse_cpu, parse_mem

from .config import Config, Target

OPT_OUT_ANNOTATION = "profiler.aks.io/skip"


@dataclass
class Candidate:
    target: Target
    namespace: str
    pod: str
    ip: str
    container: str
    image: str
    port: int
    scheme: str
    created: float = 0.0        # epoch seconds; 0 = unknown/static (age guard skipped)
    mem_limit: int = 0
    cpu_limit: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return self.namespace, self.pod

    @property
    def base_url(self) -> str:
        host = f"[{self.ip}]" if ":" in self.ip else self.ip
        return f"{self.scheme}://{host}:{self.port}"


def _is_ready(pod) -> bool:
    return any(c.type == "Ready" and c.status == "True" for c in (pod.status.conditions or []))


def _to_candidate(target: Target, pod) -> Candidate | None:
    if (pod.metadata.annotations or {}).get(OPT_OUT_ANNOTATION) == "true":
        return None
    if not pod.status.pod_ip or not _is_ready(pod):
        return None
    containers = pod.spec.containers or []
    chosen = next((c for c in containers if c.name == target.container), None) if target.container else None
    chosen = chosen or (containers[0] if containers else None)
    limits = (chosen.resources.limits or {}) if chosen and chosen.resources else {}
    return Candidate(
        target=target, namespace=pod.metadata.namespace, pod=pod.metadata.name, ip=pod.status.pod_ip,
        container=chosen.name if chosen else "", image=chosen.image if chosen else "",
        port=target.port, scheme=target.scheme,
        created=pod.metadata.creation_timestamp.timestamp() if pod.metadata.creation_timestamp else 0.0,
        mem_limit=parse_mem(limits.get("memory")), cpu_limit=parse_cpu(limits.get("cpu")),
    )


class StaticDiscovery:
    """Dev/test mode: targets are plain URLs, no Kubernetes involved."""

    def candidates(self, target: Target) -> list[Candidate]:
        out = []
        for url in target.static_urls:
            u = urlparse(url)
            out.append(Candidate(target=target, namespace="static", pod=u.netloc, ip=u.hostname or "",
                                 container=target.component, image="", port=u.port or 80,
                                 scheme=u.scheme or "http"))
        return out


class K8sDiscovery:
    def __init__(self, core_api=None):
        if core_api is None:
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()
            core_api = k8s_client.CoreV1Api()
        self.api = core_api

    def candidates(self, target: Target) -> list[Candidate]:
        if target.static_urls:
            return StaticDiscovery().candidates(target)
        kwargs = {"label_selector": target.selector, "field_selector": "status.phase=Running",
                  "limit": 500, "_request_timeout": 60}
        list_fn = (self.api.list_namespaced_pod if target.namespace else self.api.list_pod_for_all_namespaces)
        args = (target.namespace,) if target.namespace else ()
        out, cont = [], None
        while True:
            page = list_fn(*args, **kwargs, **({"_continue": cont} if cont else {}))
            out.extend(c for c in (_to_candidate(target, p) for p in page.items) if c)
            # The Kubernetes client names this field `_continue` (`continue` is a Python keyword).
            cont = page.metadata._continue  # pylint: disable=protected-access
            if not cont:
                return out


@dataclass
class Verdict:
    skip_all: str = ""   # reason; empty = profile this pod
    skip_cpu: str = ""   # reason the (intrusive) CPU profile alone is skipped
    metrics_unavailable: bool = False


class Guard:
    """Skips pods that are young or already close to their limits.

    Usage comes from the metrics API. If it is unavailable the guard fails open
    (heap/goroutine are cheap; CPU profiling a healthy pod is the common case)
    and reports metrics_unavailable so it shows up in the collector's metrics.
    """

    def __init__(self, cfg: Config, custom_api=None, now=time.time):
        self.cfg = cfg
        self.now = now
        self.api = custom_api

    def _api(self):
        if self.api is None:
            self.api = k8s_client.CustomObjectsApi()
        return self.api

    def _usage(self, cand: Candidate) -> tuple[float, int]:
        pm = self._api().get_namespaced_custom_object("metrics.k8s.io", "v1beta1", cand.namespace,
                                                      "pods", cand.pod)
        for c in pm.get("containers", []):
            if c.get("name") == cand.container:
                u = c.get("usage", {})
                return parse_cpu(u.get("cpu")), parse_mem(u.get("memory"))
        raise LookupError(f"no metrics for container {cand.container}")

    def young(self, cand: Candidate) -> bool:
        return bool(cand.created) and self.now() - cand.created < self.cfg.min_pod_age_seconds

    def evaluate(self, cand: Candidate) -> Verdict:
        if self.young(cand):
            return Verdict(skip_all="young")
        if cand.namespace == "static" or not (cand.mem_limit or cand.cpu_limit):
            return Verdict()
        try:
            cpu, mem = self._usage(cand)
        except Exception:
            return Verdict(metrics_unavailable=True)
        if cand.mem_limit and 100.0 * mem / cand.mem_limit >= self.cfg.max_memory_util_pct:
            return Verdict(skip_all="memory")
        if cand.cpu_limit and 100.0 * cpu / cand.cpu_limit >= self.cfg.max_cpu_util_pct:
            return Verdict(skip_cpu="cpu_busy")
        return Verdict()
