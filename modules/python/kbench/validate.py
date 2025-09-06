import argparse
import time

from clients.kubernetes_client import KubernetesClient


def validate(node_count, operation_timeout_in_minutes=10):
    kube_client = KubernetesClient()
    kube_client.wait_for_nodes_ready(node_count, operation_timeout_in_minutes)

def main():
    parser = argparse.ArgumentParser(description="Validate k8s setup for a kbench CRI run.")

    parser.add_argument("node_count", type=int, help="Number of desired nodes")
    parser.add_argument("operation_timeout", type=int, default=600, help="Operation timeout to wait for nodes to be ready")

    args = parser.parse_args()

    validate(args.node_count, args.operation_timeout)

if __name__ == "__main__":
    main()
