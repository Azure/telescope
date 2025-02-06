import argparse
import time

from clients.kubernetes_client import KubernetesClient


def validate(node_count, operation_timeout_in_minutes=10):
    kube_client = KubernetesClient()
    ready_node_count = 0
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    while time.time() < timeout:
        ready_nodes = kube_client.get_ready_nodes()
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.")
        if ready_node_count == node_count:
            break
        print(f"Waiting for {node_count} nodes to be ready.")
        time.sleep(10)
    if ready_node_count != node_count:
        raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")

def main():
    parser = argparse.ArgumentParser(description="Validate k8s setup for a kbench CRI run.")

    parser.add_argument("node_count", type=int, help="Number of desired nodes")
    parser.add_argument("operation_timeout", type=int, default=600, help="Operation timeout to wait for nodes to be ready")

    args = parser.parse_args()

    validate(args.node_count, args.operation_timeout)

if __name__ == "__main__":
    main()
