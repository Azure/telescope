import json
import unittest

import yaml

from agent_sandbox import manifests as mf


def deployment(name, namespace):
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "namespace": namespace},
            "spec": {"template": {"spec": {"containers": [{"name": "manager", "image": "example/controller:v1"}]}}}}


SANDBOX_RELEASE = [
    {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "agent-sandbox-system"}},
    {"apiVersion": "apiextensions.k8s.io/v1", "kind": "CustomResourceDefinition",
     "metadata": {"name": "sandboxes.agents.x-k8s.io"}},
    deployment(mf.CONTROLLER_NAME, "agent-sandbox-system"),
]
KWOK_RELEASE = [
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "kwok", "namespace": "kube-system"},
     "data": {"kwok.yaml": "apiVersion: config.kwok.x-k8s.io/v1alpha1\nkind: KwokConfiguration\n"
                           "options:\n  enableCRDs:\n  - Stage\n"}},
    deployment("kwok-controller", "kube-system"),
]


class TestReleaseDocs(unittest.TestCase):
    def test_controller(self):
        docs = mf.controller_docs(SANDBOX_RELEASE, {"agentpool": "ctrl"}, cpu_limit="6")
        spec = docs[2]["spec"]["template"]["spec"]
        self.assertEqual(spec["nodeSelector"], {"agentpool": "ctrl"})
        self.assertEqual(spec["containers"][0]["args"], mf.CONTROLLER_ARGS)
        self.assertEqual(spec["containers"][0]["resources"]["limits"], {"cpu": "6", "memory": "8Gi"})
        self.assertEqual(len(docs), len(SANDBOX_RELEASE))
        self.assertNotIn("nodeSelector", SANDBOX_RELEASE[2]["spec"]["template"]["spec"])  # input left alone

    def test_controller_requires_the_deployment(self):
        with self.assertRaises(ValueError):
            mf.controller_docs(SANDBOX_RELEASE[:2], {})

    def test_kwok(self):
        docs = mf.kwok_docs(KWOK_RELEASE, {"agentpool": "load"})
        config = yaml.safe_load(docs[0]["data"]["kwok.yaml"])
        self.assertEqual(config["options"]["podPlayStageParallelism"], 64)
        self.assertEqual(config["options"]["enableCRDs"], ["Stage"])
        self.assertEqual(config["kind"], "KwokConfiguration")
        self.assertEqual(docs[1]["spec"]["template"]["spec"]["nodeSelector"], {"agentpool": "load"})


class TestObjects(unittest.TestCase):
    def test_kwok_nodes_accept_the_template_pods(self):
        nodes = mf.kwok_nodes(3, 1000)
        self.assertEqual([n["metadata"]["name"] for n in nodes], ["kwok-0", "kwok-1", "kwok-2"])
        pod = mf.sandbox_template()["spec"]["podTemplate"]["spec"]
        node = nodes[0]
        for key, value in pod["nodeSelector"].items():
            self.assertEqual(node["metadata"]["labels"][key], value)
        (taint,) = node["spec"]["taints"]
        self.assertIn({"key": taint["key"], "operator": "Equal", "value": taint["value"], "effect": taint["effect"]},
                      pod["tolerations"])
        self.assertTrue(node["spec"]["providerID"].startswith("kwok://"))
        self.assertEqual(node["status"]["capacity"]["pods"], "1000")

    def test_pools(self):
        docs = mf.pool_docs(2, 750)
        self.assertEqual([(d["kind"], d["metadata"].get("namespace", d["metadata"]["name"])) for d in docs],
                         [("Namespace", "sbx-p0"), ("SandboxTemplate", "sbx-p0"), ("SandboxWarmPool", "sbx-p0"),
                          ("Namespace", "sbx-p1"), ("SandboxTemplate", "sbx-p1"), ("SandboxWarmPool", "sbx-p1")])
        self.assertEqual(docs[2]["spec"], {"replicas": 750, "sandboxTemplateRef": {"name": "t"}})
        self.assertEqual(docs[1]["spec"]["podTemplate"]["spec"]["runtimeClassName"], "kata-vm-isolation")
        self.assertNotIn("_source", docs[1])

    def test_plan(self):
        p = mf.plan("run1", 4, [50, 100, 2.5], 300, 60, 2)
        self.assertEqual([ph["name"] for ph in p["phases"]], ["rate-50", "rate-100", "rate-2-5"])
        self.assertEqual((p["phases"][0]["durationSeconds"], p["phases"][0]["warmupSeconds"]), (360, 60))
        self.assertEqual(p["pools"][3], {"namespace": "sbx-p3", "name": "wp"})

    def test_generator_objects(self):
        docs = mf.generator_docs({"runId": "r"}, "print(1)\n", {"agentpool": "load"})
        self.assertEqual([d["kind"] for d in docs],
                         ["Namespace", "ServiceAccount", "ClusterRole", "ClusterRoleBinding", "ConfigMap", "Pod"])
        pod = docs[-1]
        self.assertEqual(pod["spec"]["serviceAccountName"], docs[1]["metadata"]["name"])
        self.assertEqual(pod["spec"]["nodeSelector"], {"agentpool": "load"})
        self.assertEqual(json.loads(docs[4]["data"]["plan.json"]), {"runId": "r"})
        verbs = {(r["resources"][0], v) for r in docs[2]["rules"] for v in r["verbs"]}
        self.assertIn(("sandboxclaims", "create"), verbs)
        self.assertNotIn(("sandboxes", "delete"), verbs)


if __name__ == "__main__":
    unittest.main()
