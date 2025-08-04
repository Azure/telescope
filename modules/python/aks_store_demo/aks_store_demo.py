"""AKS Store Demo - Application deployment and management for AKS Store."""
import argparse
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
    tag: str = "2.0.0"

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

    def apply_manifest(self, manifest_url: str, wait_condition_type: str = None,
                          resource_type: str = None, resource_name: str = None, timeout: int = 300):
        """Apply a single manifest from URL with optional wait conditions."""
        try:
            logger.info(f"Applying manifest from URL: {manifest_url}")

            # Apply the manifest first
            execute_with_retries(
                self.k8s_client.apply_manifest_from_url,
                manifest_url=manifest_url,
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

            logger.info(f"Successfully applied manifest from URL: {manifest_url}")

        except Exception as e:
            logger.error(f"Failed to apply manifest from URL {manifest_url}: {e}")
            raise RuntimeError(f"Failed to apply manifest from URL {manifest_url}: {e}") from e

    def delete_manifest_from_url(self, manifest_url: str):
        """Delete resources from a manifest URL."""
        try:
            logger.info(f"Deleting resources from URL: {manifest_url}")

            execute_with_retries(
                self.k8s_client.delete_manifest_from_url,
                manifest_url=manifest_url,
                ignore_not_found=True,
                namespace=self.namespace
            )

            logger.info(f"Successfully deleted resources from URL: {manifest_url}")

        except Exception as e:
            logger.error(f"Failed to delete manifest from URL {manifest_url}: {e}")
            # Don't raise the exception here - we want cleanup to continue even if one manifest fails

    @abstractmethod
    def deploy(self):
        """Deploy AKS Store Demo components."""

    @abstractmethod
    def cleanup(self):
        """Clean up AKS Store Demo resources."""


@dataclass
class AllInOneAKSStoreDemo(AKSStoreDemo):
    """All-in-one AKS Store Demo implementation."""

    def get_manifest_urls(self) -> List[Dict[str, Any]]:
        """Get the list of manifest URLs to apply with their configurations."""
        # Use configurable tag instead of hardcoded commit ID
        base_url = f"https://raw.githubusercontent.com/Azure-Samples/aks-store-demo/{self.tag}"

        return [
            {
                "url": f"{base_url}/aks-store-all-in-one.yaml",
                "wait_condition_type": "available",
                "resource_type": "deployment",
                "resource_name": None, # All
                "timeout": 1200
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

            # Apply all manifests from URLs
            manifests = self.get_manifest_urls()

            for manifest_config in manifests:
                manifest_url = manifest_config["url"]

                logger.info(f"Deploying from URL: {manifest_url}")

                self.apply_manifest(
                    manifest_url=manifest_url,
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

            # Get all manifest URLs and delete in reverse order
            manifests = self.get_manifest_urls()
            manifests.reverse()  # Delete in reverse order

            for manifest_config in manifests:
                manifest_url = manifest_config["url"]
                self.delete_manifest_from_url(manifest_url)

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
        "--action",
        choices=["deploy", "cleanup"],
        required=True,
        help="Action to perform: deploy or cleanup",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default="2.0.0",
        help="Tag version of AKS Store Demo to use (default: 2.0.0)",
    )

    args = parser.parse_args()

    demo = AllInOneAKSStoreDemo(
        cluster_context=args.cluster_context,
        namespace=args.namespace,
        action=args.action,
        tag=args.tag,
    )

    if args.action == "deploy":
        demo.deploy()
    elif args.action == "cleanup":
        demo.cleanup()


if __name__ == "__main__":
    main()
