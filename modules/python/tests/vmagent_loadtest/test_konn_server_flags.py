import unittest
from unittest.mock import patch

import yaml

from vmagent_loadtest import deploy

BASE_IMAGE = "mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/server:v0.32.1-11"
CANDIDATE_IMAGE = "imranpochi/proxy-server:v0.37.0-1"
BACKEND_DIAL = "--backend-dial-timeout=30s"
WRITE_CHANNEL = "--frontend-write-channel-size=10"


def rendered_server_args(image):
    applied = []
    with patch.object(deploy, "kubectl_apply", lambda _kubeconfig, manifest: applied.append(manifest)):
        deploy.deploy_konnectivity_server("kc", "ns", server_count=2, wait=False, server_image=image)
    docs = [d for d in yaml.safe_load_all(applied[0]) if d and d.get("kind") == "Deployment"]
    return docs[0]["spec"]["template"]["spec"]["containers"][0]["args"]


class KonnServerOptionalArgsTest(unittest.TestCase):
    def test_version_gates(self):
        self.assertEqual(deploy.konn_server_optional_args(BASE_IMAGE), [])
        self.assertEqual(deploy.konn_server_optional_args("x/server:v0.35.9"), [])
        self.assertEqual(deploy.konn_server_optional_args("x/server:v0.36.0"), [BACKEND_DIAL])
        self.assertEqual(deploy.konn_server_optional_args(CANDIDATE_IMAGE), [BACKEND_DIAL, WRITE_CHANNEL])
        self.assertEqual(deploy.konn_server_optional_args("x/server:v1.0.0"), [BACKEND_DIAL, WRITE_CHANNEL])

    def test_unparseable_tag_omits_flags(self):
        self.assertEqual(deploy.konn_server_optional_args("x/server:latest"), [])
        self.assertEqual(deploy.konn_server_optional_args("x/server"), [])
        self.assertEqual(deploy.konn_server_optional_args("x/server@sha256:abc123"), [])
        self.assertEqual(deploy.konn_server_optional_args("localhost:5000/server"), [])


class KonnServerManifestTest(unittest.TestCase):
    def test_base_image_has_no_unsupported_flags(self):
        args = rendered_server_args(BASE_IMAGE)
        self.assertNotIn(BACKEND_DIAL, args)
        self.assertNotIn(WRITE_CHANNEL, args)
        self.assertIn("--enable-profiling", args)
        self.assertNotIn(None, args)

    def test_candidate_image_keeps_flags_in_order(self):
        args = rendered_server_args(CANDIDATE_IMAGE)
        self.assertIn(BACKEND_DIAL, args)
        self.assertEqual(args.index(WRITE_CHANNEL), args.index(BACKEND_DIAL) + 1)
        self.assertEqual(args[args.index(WRITE_CHANNEL) + 1], "--enable-profiling")

    def test_no_placeholder_left_behind(self):
        for image in (BASE_IMAGE, CANDIDATE_IMAGE, "x/server:latest"):
            self.assertFalse(any("__SERVER" in str(a) for a in rendered_server_args(image)))


if __name__ == "__main__":
    unittest.main()
