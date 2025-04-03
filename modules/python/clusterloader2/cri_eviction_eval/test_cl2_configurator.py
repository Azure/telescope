import unittest
from unittest.mock import MagicMock
from cl2_configurator import CL2Configurator
from data_type import  ResourceConfig

class TestCL2Configurator(unittest.TestCase):

    # generate unit test for the CL2Configurator class to test the generate_cl2_override method
    def setUp(self):
        self.max_pods = 10
        self.timeout_seconds = 300
        self.provider = "aws"
        self.node_config = MagicMock()
        self.node_config.remaining_resources = ResourceConfig(cpu=1000, memory=1000000)
        self.node_config.total_resources = ResourceConfig(cpu=2000, memory=2000000)
        self.node_config.name = "node1"

    def test_generate_cl2_override(self):
        eviction_eval = CL2Configurator(max_pods=self.max_pods, timeout_seconds=self.timeout_seconds, provider=self.provider)
        eviction_eval.generate_cl2_override(self.node_config, load_type="cpu")

        self.assertIsNotNone(eviction_eval.workload_config)
        self.assertEqual(eviction_eval.workload_config.load_type, "cpu")
        self.assertEqual(eviction_eval.workload_config.load_duration_seconds, 10 * (self.max_pods - 2))
        self.assertEqual(eviction_eval.workload_config.pod_request_resource.cpu_milli, int(1000 * 0.95 / (self.max_pods - 2)))
        self.assertEqual(eviction_eval.workload_config.load_resource.cpu_milli, int(1000 / (self.max_pods - 2) * 1.1))
        self.assertEqual(eviction_eval.workload_config.load_resource.memory_ki, int(1000000 / (self.max_pods - 2) * 1.1))

if __name__ == '__main__':
    unittest.main()


