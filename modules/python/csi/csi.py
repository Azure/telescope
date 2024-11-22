import time
import argparse
from client.kubernetes_client import KubernetesClient

def validate_node_count(node_label, node_count, operation_timeout_in_minutes):
    kube_client = KubernetesClient()
    ready_node_count = 0
    timeout = time.time() + (operation_timeout_in_minutes * 60)
    print(f"Validating {node_count} nodes with label {node_label} are ready.")
    while time.time() < timeout:
        ready_nodes = kube_client.get_ready_nodes(label_selector=node_label)
        ready_node_count = len(ready_nodes)
        print(f"Currently {ready_node_count} nodes are ready.")
        if ready_node_count == node_count:
            break
        print(f"Waiting for {node_count} nodes to be ready.")
        time.sleep(10)
    if ready_node_count != node_count:
        raise Exception(f"Only {ready_node_count} nodes are ready, expected {node_count} nodes!")

def main():
    parser = argparse.ArgumentParser(description="CSI Benchmark.")
    subparsers = parser.add_subparsers(dest="command")

    # Sub-command for validate
    parser_validate = subparsers.add_parser("validate", help="Validate node count")
    parser_validate.add_argument("node_label", type=str, help="Node label selector")
    parser_validate.add_argument("node_count", type=int, help="Number of nodes")
    parser_validate.add_argument("operation_timeout", type=int, help="Timeout for the operation in seconds")

    args = parser.parse_args()
    if args.command == "validate":
        validate_node_count(args.node_label, args.node_count, args.operation_timeout)

if __name__ == "__main__":
    main()
