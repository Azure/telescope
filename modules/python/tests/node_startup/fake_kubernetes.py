"""Fake CoreV1Api fed from JSON objects shaped like `kubectl get -o json` output.

Used by the tests and by fixtures/generate_v1_golden.py, so the v1 and v2 code
see exactly the same Kubernetes objects.
"""
import json
import threading
from types import SimpleNamespace

from kubernetes import client

API_CLIENT = client.ApiClient()


def to_model(obj, model_name):
    """Deserialize a JSON dict into a kubernetes client model (e.g. "V1Pod")."""
    return API_CLIENT.deserialize(SimpleNamespace(data=json.dumps(obj)), model_name)


def parse_field_selector(selector):
    return dict(part.split("=", 1) for part in (selector or "").split(",") if part)


def matches_labels(labels, selector):
    return all((labels or {}).get(key) == value for key, value in parse_field_selector(selector).items())


class FakeCoreV1Api:
    """Serves pods, events, logs and nodes; list filters cover the selectors the collectors use.

    `nodes` are returned by list_node (the pool before scale-up); `readable_nodes`
    can only be read by name (e.g. the node created by the scale-up).
    """

    def __init__(self, pods=(), events=(), logs=None, nodes=(), readable_nodes=(), all_namespace_pods=(),
                 metrics_text=None):
        self.pods = [to_model(pod, "V1Pod") for pod in pods]
        self.events = [to_model(event, "CoreV1Event") for event in events]
        self.logs = logs or {}
        self.nodes = [to_model(node, "V1Node") for node in nodes]
        self.readable_nodes = [to_model(node, "V1Node") for node in readable_nodes]
        self.all_namespace_pods = [to_model(pod, "V1Pod") for pod in all_namespace_pods]
        self.metrics_text = metrics_text
        self.created_namespaces = []
        self.created_pods = []
        self.deleted_pods = []
        self.api_client = None

    def list_namespaced_pod(self, namespace, label_selector=None, field_selector=None):
        fields = parse_field_selector(field_selector)
        items = [pod for pod in self.pods
                 if pod.metadata.namespace == namespace
                 and matches_labels(pod.metadata.labels, label_selector)
                 and ("spec.nodeName" not in fields or pod.spec.node_name == fields["spec.nodeName"])]
        return SimpleNamespace(items=items)

    def list_pod_for_all_namespaces(self, field_selector=None):
        node_name = parse_field_selector(field_selector).get("spec.nodeName")
        return SimpleNamespace(items=[pod for pod in self.all_namespace_pods if pod.spec.node_name == node_name])

    def read_namespaced_pod(self, name, namespace):
        for pod in self.pods:
            if pod.metadata.name == name and pod.metadata.namespace == namespace:
                return pod
        raise client.rest.ApiException(status=404)

    def list_namespaced_event(self, namespace, field_selector=None):
        fields = parse_field_selector(field_selector)
        items = [event for event in self.events
                 if event.metadata.namespace == namespace
                 and event.involved_object.name == fields.get("involvedObject.name")]
        return SimpleNamespace(items=items)

    def read_namespaced_pod_log(self, name, namespace, container, **_kwargs):
        text = self.logs.get(f"{namespace}/{name}/{container}")
        if text is None:
            raise client.rest.ApiException(status=400)
        return SimpleNamespace(data=text.encode("utf-8"))

    def list_node(self, label_selector=None, **_kwargs):
        return SimpleNamespace(items=[node for node in self.nodes
                                      if matches_labels(node.metadata.labels, label_selector)])

    def read_node(self, name):
        for node in self.nodes + self.readable_nodes:
            if node.metadata.name == name:
                return node
        raise client.rest.ApiException(status=404)

    def create_namespaced_pod(self, namespace, body):
        self.created_pods.append((namespace, body))
        return body

    def delete_namespaced_pod(self, name, namespace):
        self.deleted_pods.append((namespace, name))

    def connect_get_namespaced_pod_proxy_with_path(self, name, namespace, path):
        if self.metrics_text is None:
            raise client.rest.ApiException(status=503, reason=f"no proxy for {namespace}/{name}/{path}")
        return self.metrics_text

    def read_namespace(self, name):
        raise client.rest.ApiException(status=404, reason=f"namespace {name} not found")

    def create_namespace(self, body):
        self.created_namespaces.append(body.metadata.name)
        return body


def kubernetes_client(client_class, api):
    """A real KubernetesClient (v2, or v1 in the generator) whose CoreV1Api is `api`, without a kubeconfig."""
    k8s = client_class.__new__(client_class)
    k8s.api = api
    return k8s


class FakeWatch:
    """Stands in for kubernetes.watch.Watch, yielding the given V1Node objects as MODIFIED events."""

    def __init__(self, nodes):
        self.nodes = nodes
        self.stopped = False
        self.exhausted = threading.Event()
        self.stream_kwargs = None

    def stream(self, *_args, **kwargs):
        self.stream_kwargs = kwargs
        for node in self.nodes:
            yield {"type": "MODIFIED", "object": node}
        self.exhausted.set()

    def stop(self):
        self.stopped = True
