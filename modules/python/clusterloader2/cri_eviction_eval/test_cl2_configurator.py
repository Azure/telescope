import unittest
from unittest.mock import MagicMock
from cl2_configurator import CL2Configurator
from cri_eviction_eval.data_type import ResourceStressor
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
        resource_stresser = ResourceStressor("cpu", 1.1, "quick")
        self.resource_stresser = resource_stresser

    def test_generate_cl2_override(self):
        eviction_eval = CL2Configurator(max_pods=self.max_pods, stress_config = self.resource_stresser,
                                        timeout_seconds=self.timeout_seconds, provider=self.provider)
        eviction_eval.generate_cl2_override(self.node_config)

        self.assertIsNotNone(eviction_eval.workload_config)
        self.assertEqual(eviction_eval.workload_config.stress_config.load_type, "cpu")
        self.assertEqual(eviction_eval.workload_config.stress_config.load_duration, 10 * (self.max_pods - 2))
        self.assertEqual(eviction_eval.workload_config.resource_request.cpu_milli, int(1000 * 0.95 / (self.max_pods - 2)))
        self.assertEqual(eviction_eval.workload_config.resource_usage.cpu_milli, int(1000 / (self.max_pods - 2) * 1.1))
        self.assertEqual(eviction_eval.workload_config.resource_usage.memory_ki, int(1000000 / (self.max_pods - 2) * 1.1))

if __name__ == '__main__':
    unittest.main()


