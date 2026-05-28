"""
Azure AKS Node Pool CRUD Operations Module.

This module provides a cloud-agnostic NodePoolCRUD class for Azure Kubernetes Service (AKS)
node pools, including create, scale (up/down), and delete operations. It supports
both direct and progressive scaling operations and handles GPU-enabled node pools.
"""

import logging
import os
import time
import yaml

from clients.aks_client import AKSClient
from utils.logger_config import get_logger, setup_logging

# Configure logging
setup_logging()
logger = get_logger(__name__)
# Suppress noisy Azure SDK logs
get_logger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.ERROR)
get_logger("azure.identity").setLevel(logging.ERROR)
get_logger("azure.core.pipeline").setLevel(logging.ERROR)
get_logger("msal").setLevel(logging.ERROR)

# Workload type configuration for unified _apply_workload helper
WORKLOAD_CONFIG = {
    "deployment": {
        "template_file": "deployment.yml",
        "count_key": "DEPLOYMENT_REPLICAS",
        "resource_type": "deployment",
        "wait_condition": "available",
        "verify_pods_ready": True,
    },
    "statefulset": {
        "template_file": "statefulset.yml",
        "count_key": "STATEFULSET_REPLICAS",
        "resource_type": "statefulset",
        "wait_condition": "ready",
        "verify_pods_ready": True,
    },
    "job": {
        "template_file": "job.yml",
        "count_key": "JOB_COMPLETIONS",
        "resource_type": "job",
        "wait_condition": "complete",
        "verify_pods_ready": False,  # Job pods terminate after completion
    },
}

class NodePoolCRUD:
    """Performs AKS node pool operations - metrics collection is handled directly by AKSClient"""

    def __init__(
        self, resource_group, kube_config_file=None, result_dir=None, step_timeout=600
    ):
        """Initialize with Azure resource identifiers"""
        self.resource_group = resource_group
        self.aks_client = AKSClient(
            resource_group=resource_group,
            kube_config_file=kube_config_file,
            result_dir=result_dir,
            operation_timeout_minutes=step_timeout / 60,  # Convert seconds to minutes
        )

        if not self.aks_client:
            error_msg = "Failed to initialize AKS client."
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Get the cluster name when initializing
        self.cluster_name = self.aks_client.get_cluster_name()
        self.step_timeout = step_timeout

    def create_node_pool(
        self, node_pool_name, vm_size, node_count=1, gpu_node_pool=False
    ):
        """
        Create a new node pool

        Args:
            node_pool_name: Name of the node pool
            vm_size: VM size for the nodes
            node_count: Number of nodes to create (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)

        Returns:
            The created node pool object or False if creation failed
        """
        logger.info(
            f"Creating node pool '{node_pool_name}' with {node_count} nodes (GPU: {gpu_node_pool})"
        )

        try:
            result = self.aks_client.create_node_pool(
                node_pool_name=node_pool_name,
                vm_size=vm_size,
                node_count=node_count,
                gpu_node_pool=gpu_node_pool,
            )
            logger.info(f"Node pool '{node_pool_name}' created successfully")
            return result
        except Exception as e:
            logger.error(f"Failed to create node pool '{node_pool_name}': {str(e)}")
            return False

    def scale_node_pool(
        self,
        node_pool_name,
        node_count,
        progressive=False,
        scale_step_size=1,
        gpu_node_pool=False,
    ):
        """
        Scale a node pool to specified count

        Args:
            node_pool_name: Name of the node pool
            node_count: Desired node count
            progressive: Whether to scale progressively in steps (default: False)
            scale_step_size: Number of nodes to add/remove in each step if progressive (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)

        Returns:
            The scaled node pool object or False if scaling failed
        """
        try:
            logger.info(
                f"Scaling node pool '{node_pool_name}' to {node_count} nodes (Progressive: {progressive})"
            )

            result = self.aks_client.scale_node_pool(
                node_pool_name=node_pool_name,
                node_count=node_count,
                gpu_node_pool=gpu_node_pool,
                progressive=progressive,
                scale_step_size=scale_step_size,
            )

            if result is not None:
                logger.info(
                    f"Node pool '{node_pool_name}' scaled to {node_count} nodes successfully"
                )

            return result
        except Exception as e:
            logger.error(f"Failed to scale node pool '{node_pool_name}': {str(e)}")
            return False

    def delete_node_pool(self, node_pool_name):
        """
        Delete a node pool

        Args:
            node_pool_name: Name of the node pool

        Returns:
            True if deletion was successful, False otherwise
        """
        logger.info(f"Deleting node pool '{node_pool_name}'")

        try:
            result = self.aks_client.delete_node_pool(node_pool_name=node_pool_name)

            logger.info(f"Node pool '{node_pool_name}' deleted successfully")
            return result
        except Exception as e:
            logger.error(f"Failed to delete node pool '{node_pool_name}': {str(e)}")
            return False

    def all(
        self,
        node_pool_name,
        vm_size=None,
        node_count=None,
        target_count=None,
        progressive=False,
        scale_step_size=1,
        gpu_node_pool=False,
        step_wait_time=30,
    ):
        """
        Unified method to perform all node pool operations: create, scale-up, scale-down, delete
        It will perform all operations in sequence with a 30-second gap between each.

        Args:
            node_pool_name: Name of the node pool
            vm_size: VM size for nodes (required for create operation)
            node_count: Number of nodes to create (for create operation, default: 0)
            target_count: Target node count for scaling operations
            progressive: Whether to scale progressively in steps (default: False)
            scale_step_size: Number of nodes to add/remove in each step if progressive (default: 1)
            gpu_node_pool: Whether this is a GPU-enabled node pool (default: False)
            step_wait_time: Time to wait between operations (default: 30 seconds)

        Returns:
            True if all operations succeeded, False if any operation failed
        """
        errors = []
        results = {
            "create": False,
            "scale_up": False,
            "scale_down": False,
            "delete": False,
        }

        try:
            # 1. Create node pool
            logger.info(f"Starting to create node pool '{node_pool_name}'")
            create_result = self.create_node_pool(
                node_pool_name=node_pool_name,
                vm_size=vm_size,
                node_count=node_count,
                gpu_node_pool=gpu_node_pool,
            )
            results["create"] = create_result

            if create_result is False:
                error_msg = f"Create node pool operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)
                return False

            logger.info(f"Waiting {step_wait_time} seconds before scaling up...")
            time.sleep(step_wait_time)

            # 2. Scale up
            logger.info(
                f"Scaling up node pool '{node_pool_name}' to {target_count} nodes"
            )
            scale_up_result = self.scale_node_pool(
                node_pool_name=node_pool_name,
                node_count=target_count,
                progressive=progressive,
                scale_step_size=scale_step_size,
                gpu_node_pool=gpu_node_pool,
            )
            results["scale_up"] = scale_up_result

            if scale_up_result is False:
                error_msg = f"Scale up operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)
                # Continue to scale down and delete to clean up resources

            logger.info(f"Waiting {step_wait_time} seconds before scaling down...")
            time.sleep(step_wait_time)

            # 3. Scale down (back to original count)
            logger.info(
                f"Scaling down node pool '{node_pool_name}' back to {node_count} nodes"
            )
            scale_down_result = self.scale_node_pool(
                node_pool_name=node_pool_name,
                node_count=node_count,
                progressive=progressive,
                scale_step_size=scale_step_size,
                gpu_node_pool=gpu_node_pool,
            )
            results["scale_down"] = scale_down_result

            if scale_down_result is False:
                error_msg = f"Scale down operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)
                # Continue to delete to clean up resources

            logger.info(f"Waiting {step_wait_time} seconds before deleting...")
            time.sleep(step_wait_time)

            # 4. Delete node pool
            logger.info(f"Deleting node pool '{node_pool_name}'")
            delete_result = self.delete_node_pool(node_pool_name=node_pool_name)
            results["delete"] = delete_result

            if delete_result is False:
                error_msg = f"Delete operation failed for '{node_pool_name}'"
                logger.error(error_msg)
                errors.append(error_msg)

            # Check overall success
            if all(results.values()):
                logger.info(
                    "All operations completed successfully for node pool '%s'",
                    node_pool_name,
                )
                return True

            failed_ops = [op for op, result in results.items() if result is False]
            logger.error("The following operations failed: %s", ", ".join(failed_ops))
            return False

        except Exception as e:
            error_msg = f"Failed to perform operations on node pool '{node_pool_name}': {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)
            return False

    def create_deployment(
        self,
        node_pool_name,
        replicas=10,
        manifest_dir=None,
        number_of_deployments=1,
        label_selector="app=nginx-container",
        namespace="default"
    ):
        """
        Create Kubernetes deployments after node pool operations.

        Args:
            node_pool_name: Name of the node pool to target
            replicas: Number of deployment replicas per deployment (default: 10)
            manifest_dir: Directory containing Kubernetes manifest files
            number_of_deployments: Number of deployments to create (default: 1)
            label_selector: Label selector used to target the deployment workload
            namespace: Kubernetes namespace (default: "default")

        Returns:
            True if all deployment creations were successful, False otherwise
        """
        return self._create_workloads(
            workload_type="deployment",
            node_pool_name=node_pool_name,
            count=replicas,
            number_of_workloads=number_of_deployments,
            manifest_dir=manifest_dir,
            label_selector=label_selector,
            namespace=namespace
        )

    def create_statefulset(
        self,
        node_pool_name,
        replicas=10,
        manifest_dir=None,
        number_of_statefulsets=1,
        label_selector="app=nginx-container",
        namespace="default"
    ):
        """
        Create Kubernetes StatefulSets after node pool operations.

        Args:
            node_pool_name: Name of the node pool to target
            namespace: Kubernetes namespace (default: "default")
            replicas: Number of replicas for the StatefulSet (default: 10)
            manifest_dir: Directory containing Kubernetes manifest files
            number_of_statefulsets: Number of StatefulSets to create (default: 1)
            label_selector: Label selector for pods (default: "app=nginx-container")

        Returns:
            True if all StatefulSet creations were successful, False otherwise
        """
        return self._create_workloads(
            workload_type="statefulset",
            node_pool_name=node_pool_name,
            count=replicas,
            number_of_workloads=number_of_statefulsets,
            manifest_dir=manifest_dir,
            label_selector=label_selector,
            namespace=namespace
        )

    def create_job(
        self,
        node_pool_name,
        completions=1,
        manifest_dir=None,
        number_of_jobs=1,
        label_selector="app=nginx-container",
        namespace="default"
    ):
        """
        Create Kubernetes Jobs after node pool operations.

        Args:
            node_pool_name: Name of the node pool to target
            completions: Number of job completions (default: 1)
            manifest_dir: Directory containing Kubernetes manifest files
            number_of_jobs: Number of Jobs to create (default: 1)
            label_selector: Label selector for pods (default: "app=nginx-container")
            namespace: Kubernetes namespace (default: "default")

        Returns:
            True if all Job creations were successful, False otherwise
        """
        return self._create_workloads(
            workload_type="job",
            node_pool_name=node_pool_name,
            count=completions,
            number_of_workloads=number_of_jobs,
            manifest_dir=manifest_dir,
            label_selector=label_selector,
            namespace=namespace
        )

    def _create_workloads(
        self,
        workload_type,
        node_pool_name,
        count,
        number_of_workloads,
        manifest_dir,
        label_selector,
        namespace
    ):
        """Unified helper to create multiple workload instances.

        Args:
            workload_type: Type of workload ("deployment", "statefulset", or "job")
            node_pool_name: Name of the target node pool
            count: Number of replicas/completions per workload instance
            number_of_workloads: Total number of workload instances to create
            manifest_dir: Optional custom manifest directory
            label_selector: Base label selector (e.g., "app=nginx-container")
            namespace: Kubernetes namespace

        Returns:
            True if all workloads created successfully, False otherwise
        """
        workload_type_display = workload_type.capitalize()
        logger.info("Creating %d %s(s)", number_of_workloads, workload_type_display)
        logger.info("Target node pool: %s", node_pool_name)
        logger.info("Replicas per %s: %d", workload_type, count)
        logger.info("Using manifest directory: %s", manifest_dir)

        k8s_client = self.aks_client.k8s_client
        if not k8s_client:
            logger.error("Kubernetes client not available")
            return False

        successes = 0
        for index in range(1, number_of_workloads + 1):
            logger.info("Creating %s %d/%d", workload_type, index, number_of_workloads)
            try:
                self._apply_workload(
                    k8s_client=k8s_client,
                    workload_type=workload_type,
                    node_pool_name=node_pool_name,
                    index=index,
                    count=count,
                    manifest_dir=manifest_dir,
                    label_selector=label_selector,
                    namespace=namespace
                )
                successes += 1
            except Exception as e:
                logger.error("Failed to create %s %d: %s", workload_type, index, e)
                continue

        if successes == number_of_workloads:
            logger.info("Successfully created all %d %s(s)", number_of_workloads, workload_type_display)
            return True
        logger.warning("Created %d/%d %s(s)", successes, number_of_workloads, workload_type_display)
        return False

    def _apply_workload(
        self,
        k8s_client,
        workload_type,
        node_pool_name,
        index,
        count,
        manifest_dir,
        label_selector,
        namespace
    ):
        """Unified helper to apply and verify a single workload instance.

        Args:
            k8s_client: Kubernetes client instance
            workload_type: Type of workload ("deployment", "statefulset", or "job")
            node_pool_name: Name of the target node pool
            index: Workload instance index (1-based)
            count: Number of replicas/completions
            manifest_dir: Optional custom manifest directory
            label_selector: Base label selector (e.g., "app=nginx-container")
            namespace: Kubernetes namespace

        Raises:
            ValueError: If workload_type is not in WORKLOAD_CONFIG
            TimeoutError: If workload fails to reach ready state
        """
        if workload_type not in WORKLOAD_CONFIG:
            raise ValueError(f"Unknown workload type: {workload_type}")

        config = WORKLOAD_CONFIG[workload_type]

        # Resolve template path
        if manifest_dir:
            template_path = f"{manifest_dir}/{config['template_file']}"
        else:
            template_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "workload_templates", config["template_file"]
            )

        # Generate resource name and label
        resource_name = f"myapp-{node_pool_name}-{index}"
        workload_label = f"{label_selector.split('=', 1)[-1]}-{workload_type}-{index}"

        # Render template
        rendered_template = k8s_client.create_template(
            template_path,
            {
                config["count_key"]: count,
                "NODE_POOL_NAME": node_pool_name,
                "INDEX": index,
                "LABEL_VALUE": workload_label,
            }
        )

        # Apply each document in the rendered multi-doc template
        for doc in yaml.safe_load_all(rendered_template):
            if doc:
                k8s_client.apply_manifest_from_file(manifest_dict=doc, namespace=namespace)

        logger.info("Applied manifest for %s %s", workload_type, resource_name)

        # Wait for workload to reach target condition
        logger.info("Waiting for %s %s to become %s...",
                    workload_type, resource_name, config["wait_condition"])
        ready = k8s_client.wait_for_condition(
            resource_type=config["resource_type"],
            wait_condition_type=config["wait_condition"],
            resource_name=resource_name,
            namespace=namespace,
            timeout_seconds=self.step_timeout
        )

        if not ready:
            raise TimeoutError(
                f"{workload_type.capitalize()} {resource_name} failed to become "
                f"{config['wait_condition']} within timeout"
            )

        logger.info("%s %s is successfully %s",
                    workload_type.capitalize(), resource_name, config["wait_condition"])

        # Wait for pods if configured (skipped for Jobs)
        if config["verify_pods_ready"]:
            logger.info("Waiting for pods of %s %s to be ready...", workload_type, resource_name)
            k8s_client.wait_for_pods_ready(
                operation_timeout_in_minutes=5,
                namespace=namespace,
                pod_count=count,
                label_selector=f"app={workload_label}"
            )

        logger.info("Successfully created and verified %s %d", workload_type, index)
