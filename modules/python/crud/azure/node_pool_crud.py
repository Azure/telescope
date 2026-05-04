"""
Azure AKS Node Pool CRUD Operations Module.

This module provides a cloud-agnostic NodePoolCRUD class for Azure Kubernetes Service (AKS)
node pools, including create, scale (up/down), and delete operations. It supports
both direct and progressive scaling operations and handles GPU-enabled node pools.
"""

import logging
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
            deployment_name: Base name for the deployments
            namespace: Kubernetes namespace (default: "default")
            replicas: Number of deployment replicas per deployment (default: 10)
            manifest_dir: Directory containing Kubernetes manifest files
            number_of_deployments: Number of deployments to create (default: 1)

        Returns:
            True if all deployment creations were successful, False otherwise
        """
        logger.info("Creating %d deployment(s)", number_of_deployments)
        logger.info("Target node pool: %s", node_pool_name)
        logger.info("Replicas per deployment: %d", replicas)
        logger.info("Using manifest directory: %s", manifest_dir)

        try:
            # Get Kubernetes client from AKS client
            k8s_client = self.aks_client.k8s_client

            if not k8s_client:
                logger.error("Kubernetes client not available")
                return False

            successful_deployments = 0

            # Loop through number of deployments
            for deployment_index in range(1, number_of_deployments + 1):
                logger.info("Creating deployment %d/%d", deployment_index, number_of_deployments)

                try:
                    if manifest_dir:
                        # Use the template path from manifest_dir
                        template_path = f"{manifest_dir}/deployment.yml"
                    else:
                        # Use default template path
                        template_path = "modules/python/crud/workload_templates/deployment.yml"

                    # Generate deployment name
                    deployment_name = f"myapp-{node_pool_name}-{deployment_index}"

                    # Create deployment template using k8s_client.create_template
                    deployment_template = k8s_client.create_template(
                        template_path,
                        {
                            "DEPLOYMENT_REPLICAS": replicas,
                            "NODE_POOL_NAME": node_pool_name,
                            "INDEX": deployment_index,
                            "LABEL_VALUE": label_selector.split("=", 1)[-1],
                        }
                    )

                    # Apply each document in the rendered multi-doc template
                    for doc in yaml.safe_load_all(deployment_template):
                        if doc:
                            k8s_client.apply_manifest_from_file(manifest_dict=doc)

                    logger.info("Applied manifest for deployment %s", deployment_name)

                    # Wait for deployment to be available (successful deployment verification)
                    logger.info("Waiting for deployment %s to become available...", deployment_name)
                    deployment_ready = k8s_client.wait_for_condition(
                        resource_type="deployment",
                        wait_condition_type="available",
                        resource_name=deployment_name,
                        namespace=namespace,
                        timeout_seconds=self.step_timeout
                    )

                    if deployment_ready:
                        logger.info("Deployment %s is successfully available", deployment_name)

                        # Additionally wait for pods to be ready
                        logger.info("Waiting for pods of deployment %s to be ready...", deployment_name)
                        k8s_client.wait_for_pods_ready(
                            operation_timeout_in_minutes=5,
                            namespace=namespace,
                            pod_count=replicas,
                            label_selector=label_selector
                        )

                        logger.info("Successfully created and verified deployment %d", deployment_index)
                        successful_deployments += 1
                    else:
                        logger.error("Deployment %s failed to become available within timeout", deployment_name)
                        continue

                except Exception as e:
                    logger.error("Failed to create deployment %d: %s", deployment_index, e)
                    # Continue with next deployment instead of failing completely
                    continue

            # Check if all deployments were successful
            if successful_deployments == number_of_deployments:
                logger.info("Successfully created all %d deployment(s)", number_of_deployments)
                return True
            if successful_deployments > 0:
                logger.warning("Created %d/%d deployment(s)", successful_deployments, number_of_deployments)
                return False
            logger.error("Failed to create any deployments")
            return False

        except Exception as e:
            logger.error("Failed to create deployments: %s", e)
            return False
        
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
        Create Kubernetes jobs after node pool operations.

        Args:
            node_pool_name: Name of the node pool to target
            job_name: Base name for the jobs
            namespace: Kubernetes namespace (default: "default")
            completions: Number of job completions (default: 1)
            manifest_dir: Directory containing Kubernetes manifest files
            number_of_jobs: Number of jobs to create (default: 1)

        Returns:
            True if all job creations were successful, False otherwise
        """
        logger.info("Creating %d job(s)", number_of_jobs)
        logger.info("Target node pool: %s", node_pool_name)
        logger.info("Job completions: %d", completions)
        logger.info("Using manifest directory: %s", manifest_dir)

        try:
            # Get Kubernetes client from AKS client
            k8s_client = self.aks_client.k8s_client

            if not k8s_client:
                logger.error("Kubernetes client not available")
                return False

            successful_jobs = 0

            # Loop through number of jobs
            for job_index in range(1, number_of_jobs + 1):
                logger.info("Creating job %d/%d", job_index, number_of_jobs)

                try:
                    if manifest_dir:
                        # Use the template path from manifest_dir
                        template_path = f"{manifest_dir}/job.yml"
                    else:
                        # Use default template path
                        template_path = "modules/python/crud/workload_templates/job.yml"

                    # Generate job name
                    job_name = f"myapp-{node_pool_name}-{job_index}"

                    # Create job template using k8s_client.create_template
                    job_template = k8s_client.create_template(
                        template_path,
                        {
                            "JOB_COMPLETIONS": completions,
                            "NODE_POOL_NAME": node_pool_name,
                            "INDEX": job_index,
                            "LABEL_VALUE": label_selector.split("=", 1)[-1],
                        }
                    )

                    # Apply each document in the rendered multi-doc template
                    for doc in yaml.safe_load_all(job_template):
                        if doc:
                            k8s_client.apply_manifest_from_file(manifest_dict=doc)

                    logger.info("Applied manifest for job %s", job_name)

                    # Wait for job to complete (successful job verification)
                    logger.info("Waiting for job %s to complete...", job_name)
                    job_ready = k8s_client.wait_for_condition(
                        resource_type="job",
                        wait_condition_type="complete",
                        resource_name=job_name,
                        namespace=namespace,
                        timeout_seconds=self.step_timeout
                    )

                    if job_ready:
                        logger.info("Job %s is successfully complete", job_name)
                        logger.info("Successfully created and verified job %d", job_index)
                        successful_jobs += 1
                    else:
                        logger.error("Job %s failed to complete within timeout", job_name)
                        continue

                except Exception as e:
                    logger.error("Failed to create job %d: %s", job_index, e)
                    # Continue with next job instead of failing completely
                    continue

            # Check if all jobs were successful
            if successful_jobs == number_of_jobs:
                logger.info("Successfully created all %d job(s)", number_of_jobs)
                return True
            if successful_jobs > 0:
                logger.warning("Created %d/%d job(s)", successful_jobs, number_of_jobs)
                return False
            logger.error("Failed to create any jobs")
            return False

        except Exception as e:
            logger.error("Failed to create jobs: %s", e)
            return False
