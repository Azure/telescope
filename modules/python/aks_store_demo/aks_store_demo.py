"""AKS Store Demo - Application deployment and management for AKS Store."""
import argparse
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any

from clients.kubernetes_client import KubernetesClient
from utils.retries import execute_with_retries
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)


@dataclass
class AKSStoreDemo(ABC):
    """Abstract base class for AKS Store Demo components."""
    k8s_client: KubernetesClient = None
    cluster_context: str = ""
    namespace: str = "aks-store-demo"
    action: str = "apply"
    timeout_seconds: int = 900

    def __post_init__(self):
        """Initialize the Kubernetes client after dataclass initialization."""
        if self.k8s_client is None:
            self.k8s_client = KubernetesClient()

    def set_context(self):
        """Set the Kubernetes cluster context if specified."""
        if self.cluster_context:
            logger.info(f"Setting Kubernetes context to: {self.cluster_context}")
            execute_with_retries(
                self.k8s_client.set_context,
                self.cluster_context
            )

    def ensure_namespace(self):
        """Ensure the namespace exists."""
        try:
            logger.info(f"Ensuring namespace '{self.namespace}' exists")
            execute_with_retries(
                self.k8s_client.create_namespace,
                self.namespace
            )
        except Exception as e:
            logger.warning(f"Namespace operation: {e}")

    def apply_manifest(self, manifest_file: str, wait_condition_type: str = None,
                      resource_type: str = None, resource_name: str = None, timeout: int = 300):
        """Apply a single manifest with optional wait conditions."""
        try:
            logger.info(f"Applying manifest: {manifest_file}")

            # Apply the manifest first
            execute_with_retries(
                self.k8s_client.apply_manifest_from_file,
                manifest_path=manifest_file,
                namespace=self.namespace
            )

            # Wait for condition if specified
            if wait_condition_type and resource_type:
                resource_identifier = f"{resource_type}/{resource_name}" if resource_name else resource_type
                logger.info(f"Waiting for {resource_identifier} with condition {wait_condition_type}")

                result = execute_with_retries(
                    self.k8s_client.wait_for_condition,
                    resource_type=resource_type,
                    resource_name=resource_name,
                    wait_condition_type=wait_condition_type,
                    namespace=self.namespace,
                    timeout_seconds=timeout
                )

                if not result:
                    logger.warning(f"Timeout waiting for {resource_identifier} with condition {wait_condition_type}")

            logger.info(f"Successfully applied manifest: {manifest_file}")

        except Exception as e:
            logger.error(f"Failed to apply manifest {manifest_file}: {e}")
            raise RuntimeError(f"Failed to apply manifest {manifest_file}: {e}") from e

    @abstractmethod
    def deploy(self):
        """Deploy AKS Store Demo components."""

    @abstractmethod
    def cleanup(self):
        """Clean up AKS Store Demo resources."""


@dataclass
class SingleClusterDemo(AKSStoreDemo):
    """Single cluster AKS Store Demo implementation."""
    manifests_path: str = ""

    def get_manifest_files(self) -> List[Dict[str, Any]]:
        """Get the list of manifest files to apply with their configurations."""
        base_path = self.manifests_path

        return [
            {
                "file": f"{base_path}/aks-store-all-in-one.yaml",
                "wait_condition_type": "available",
                "resource_type": "deployment",
                "resource_name": None, # All
                "timeout": 1200
            },
            {
                "file": f"{base_path}/aks-store-virtual-worker.yaml",
                "wait_condition_type": "available",
                "resource_type": "deployment",
                "resource_name": "virtual-worker",
                "timeout": 120
            },
            {
                "file": f"{base_path}/aks-store-virtual-customer.yaml",
                "wait_condition_type": "available",
                "resource_type": "deployment",
                "resource_name": "virtual-customer",
                "timeout": 120
            }
        ]

    def deploy(self):
        """Deploy all AKS Store Demo components."""
        try:
            logger.info("Starting AKS Store Demo deployment")

            # Set context if specified
            self.set_context()

            # Ensure namespace exists
            self.ensure_namespace()

            # Apply all manifests
            manifests = self.get_manifest_files()

            for manifest_config in manifests:
                manifest_file = manifest_config["file"]

                # Check if manifest file exists
                if not os.path.exists(manifest_file):
                    logger.warning(f"Manifest file not found: {manifest_file}")
                    continue

                self.apply_manifest(
                    manifest_file=manifest_file,
                    wait_condition_type=manifest_config.get("wait_condition_type"),
                    resource_type=manifest_config.get("resource_type"),
                    resource_name=manifest_config.get("resource_name"),
                    timeout=manifest_config.get("timeout", 300)
                )

            logger.info("AKS Store Demo deployment completed successfully")

        except Exception as e:
            logger.error(f"Failed to deploy AKS Store Demo: {e}")
            raise RuntimeError(f"Failed to deploy AKS Store Demo: {e}") from e

    def cleanup(self):
        """Clean up AKS Store Demo resources."""
        try:
            logger.info("Starting AKS Store Demo cleanup")

            # Set context if specified
            self.set_context()

            # Get all manifest files and delete in reverse order
            manifests = self.get_manifest_files()
            manifests.reverse()  # Delete in reverse order

            for manifest_config in manifests:
                manifest_file = manifest_config["file"]

                if not os.path.exists(manifest_file):
                    logger.warning(f"Manifest file not found for cleanup: {manifest_file}")
                    continue

                try:
                    logger.info(f"Deleting resources from: {manifest_file}")
                    execute_with_retries(
                        self.k8s_client.delete_manifest_from_file,
                        manifest_path=manifest_file,
                        namespace=self.namespace,
                        ignore_not_found=True
                    )
                    logger.info(f"Successfully deleted resources from: {manifest_file}")

                except Exception as e:
                    logger.warning(f"Failed to cleanup manifest {manifest_file}: {e}")

            logger.info("AKS Store Demo cleanup completed")

        except Exception as e:
            logger.error(f"Failed to cleanup AKS Store Demo: {e}")
            raise RuntimeError(f"Failed to cleanup AKS Store Demo: {e}") from e


def main():
    """Main function to handle command-line arguments and execute AKS Store Demo operations."""
    parser = argparse.ArgumentParser(
        description="AKS Store Demo - Application deployment and management"
    )
    parser.add_argument(
        "--cluster-context",
        type=str,
        default="",
        help="Kubernetes cluster context to use",
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="aks-store-demo",
        help="Kubernetes namespace to deploy to",
    )
    parser.add_argument(
        "--manifests-path",
        type=str,
        required=True,
        help="Path to the directory containing manifests",
    )
    parser.add_argument(
        "--action",
        choices=["deploy", "cleanup"],
        required=True,
        help="Action to perform: deploy or cleanup",
    )

    args = parser.parse_args()

    demo = SingleClusterDemo(
        cluster_context=args.cluster_context,
        namespace=args.namespace,
        manifests_path=args.manifests_path,
        action=args.action,
    )

    if args.action == "deploy":
        demo.deploy()
    elif args.action == "cleanup":
        demo.cleanup()


if __name__ == "__main__":
    main()
