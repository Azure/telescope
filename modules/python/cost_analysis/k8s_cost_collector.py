"""
Kubernetes Cost Analysis Collector

Deploy OpenCost services and collect cost analysis data.
"""

import os
import sys
import time
import socket
import subprocess
import argparse
import requests

from clients.kubernetes_client import KubernetesClient
from cost_analysis.opencost_live_exporter import OpenCostLiveExporter
from utils.logger_config import get_logger, setup_logging


# Configure logging
setup_logging()
logger = get_logger(__name__)


class OpenCostKubernetesCollector:
    """
    Handles OpenCost deployment and cost data collection using Kubernetes Python client.
    """

    def __init__(self, cluster_context: str = None):
        """
        Initialize the collector with optional cluster context.
        
        Args:
            cluster_context (str): Kubernetes cluster context to use
        """
        self.k8s_client = KubernetesClient()
        self.cluster_context = cluster_context
        self.port_forward_process = None

        # Set cluster context if provided
        if cluster_context:
            self.k8s_client.set_context(cluster_context)
            logger.info(f"Using cluster context: {cluster_context}")

    def _find_free_port(self) -> int:
        """
        Find a free port on the local machine.
        
        Returns:
            int: A free port number
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    def deploy_opencost_service(self, manifest_path: str) -> bool:
        """
        Deploy the OpenCost service using the provided YAML manifest.
        
        Args:
            manifest_path (str): Path to the OpenCost service YAML manifest
            
        Returns:
            bool: True if deployment was successful, False otherwise
        """
        try:
            logger.info(f"Deploying OpenCost service from manifest: {manifest_path}")

            # Apply the manifest using the kubernetes client
            self.k8s_client.apply_manifest_from_file(manifest_path=manifest_path)
            logger.info("Successfully deployed OpenCost service")
            return True

        except Exception as e:
            logger.error(f"Failed to deploy OpenCost service: {str(e)}")
            return False

    def wait_for_service_ready(self, service_name: str = "opencost-service",
                              namespace: str = "kube-system", timeout: int = 60) -> bool:
        """
        Wait for the OpenCost service to be ready.
        
        Args:
            service_name (str): Name of the service to wait for
            namespace (str): Namespace where the service is deployed
            timeout (int): Timeout in seconds
            
        Returns:
            bool: True if service is ready, False if timeout
        """
        logger.info(f"Waiting for service {service_name} to be ready...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                service = self.k8s_client.api.read_namespaced_service(
                    name=service_name, 
                    namespace=namespace
                )

                # Check if service has a cluster IP
                if service.spec.cluster_ip and service.spec.cluster_ip != "None":
                    logger.info(f"Service {service_name} is ready with ClusterIP: {service.spec.cluster_ip}")
                    return True

            except Exception as e:
                logger.debug(f"Service not ready yet: {str(e)}")

            time.sleep(5)

        logger.error(f"Service {service_name} did not become ready within {timeout} seconds")
        return False

    def start_port_forward(self, service_name: str = "opencost-service",
                          namespace: str = "kube-system", target_port: int = 9003) -> int:
        """
        Start port forwarding to the OpenCost service.
        
        Args:
            service_name (str): Name of the service to port-forward to
            namespace (str): Namespace where the service is deployed
            target_port (int): Target port on the service
            
        Returns:
            int: Local port number if successful, None if failed
        """
        try:
            # Find a free local port
            local_port = self._find_free_port()
            logger.info(f"Starting port-forward on local port: {local_port}")

            # Build kubectl port-forward command
            kubectl_cmd = [
                "kubectl", "port-forward", 
                f"service/{service_name}", 
                f"{local_port}:{target_port}",
                "-n", namespace
            ]

            # Add context if specified
            if self.cluster_context:
                kubectl_cmd.extend(["--context", self.cluster_context])

            # Start port-forward in background
            self.port_forward_process = subprocess.Popen(
                kubectl_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True  # Safer alternative to preexec_fn
            )

            # Wait for port-forward to be ready
            self._wait_for_port_forward_ready(local_port)

            logger.info(f"Port-forward established: localhost:{local_port} -> {service_name}:{target_port}")
            return local_port

        except Exception as e:
            logger.error(f"Failed to start port-forward: {str(e)}")
            self.cleanup_port_forward()
            return None

    def _wait_for_port_forward_ready(self, local_port: int, timeout: int = 60):
        """
        Wait for port-forward to be ready by checking the health endpoint.
        
        Args:
            local_port (int): Local port to check
            timeout (int): Timeout in seconds
        """
        logger.info("Waiting for port-forward to be ready...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"http://localhost:{local_port}/healthz", timeout=5)
                if response.status_code == 200:
                    logger.info("Port-forward is ready")
                    return
            except Exception:
                pass

            time.sleep(5)

        raise Exception(f"Port-forward failed to become ready within {timeout} seconds")

    def cleanup_port_forward(self):
        """Clean up the port-forward process."""
        if self.port_forward_process:
            try:
                # Terminate the process
                self.port_forward_process.terminate()
                try:
                    self.port_forward_process.wait(timeout=10)
                    logger.info("Port-forward process cleaned up")
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't terminate gracefully
                    self.port_forward_process.kill()
                    self.port_forward_process.wait()
                    logger.info("Port-forward process force killed")
            except Exception as e:
                logger.error(f"Error cleaning up port-forward: {str(e)}")
            finally:
                self.port_forward_process = None

    def collect_cost_data(self, window: str, aggregate: str, scenario_name: str,
                         run_id: str, metadata: dict, allocation_output: str,
                         assets_output: str, local_port: int, validate_availability: bool = True) -> bool:
        """
        Collect cost data using the OpenCost Live Exporter.
        
        Args:
            window (str): Time window for data collection
            aggregate (str): Aggregation level
            scenario_name (str): Scenario name
            run_id (str): Run ID
            metadata (dict): Additional metadata
            allocation_output (str): Output file for allocation data
            assets_output (str): Output file for assets data
            local_port (int): Local port where OpenCost is available
            validate_availability (bool): Whether to validate data availability
            
        Returns:
            bool: True if collection was successful, False otherwise
        """
        try:
            logger.info("Starting cost data collection...")

            # Create OpenCost exporter instance with metadata
            exporter = OpenCostLiveExporter(
                endpoint=f"http://localhost:{local_port}",
                run_id=run_id,
                scenario_name=scenario_name,
                metadata=metadata
            )

            # Collect allocation data
            logger.info("Collecting allocation data...")
            exporter.export_allocation_live_data(
                window=window,
                aggregate=aggregate,
                filename=allocation_output,
                validate_availability=validate_availability
            )

            # Collect assets data
            logger.info("Collecting assets data...")
            exporter.export_assets_live_data(
                window=window,
                aggregate=aggregate,
                filename=assets_output
            )

            # Check if files were created successfully
            if os.path.exists(allocation_output) and os.path.exists(assets_output):
                logger.info("Cost data collection completed successfully")

                # Display collected data
                logger.info("Allocation Costs:")
                with open(allocation_output, 'r', encoding='utf-8') as f:
                    logger.info(f.read())

                logger.info("Assets:")
                with open(assets_output, 'r', encoding='utf-8') as f:
                    logger.info(f.read())

                return True
            else:
                logger.error("Cost data collection failed - output files not created")
                return False

        except Exception as e:
            logger.error(f"Error during cost data collection: {str(e)}")
            return False

    def run_collection(self, manifest_path: str, window: str, aggregate: str,
                      scenario_name: str, run_id: str, metadata: dict,
                      result_dir: str, validate_availability: bool = True) -> dict:
        """
        Run the complete cost collection process.
        
        Args:
            manifest_path (str): Path to OpenCost service manifest
            window (str): Time window for data collection
            aggregate (str): Aggregation level
            scenario_name (str): Scenario name
            run_id (str): Run ID
            metadata (dict): Additional metadata
            result_dir (str): Directory to save results
            validate_availability (bool): Whether to validate data availability
            
        Returns:
            dict: Result containing file paths and success status
        """
        result = {
            'success': False,
            'allocation_file': None,
            'assets_file': None,
            'error': None
        }

        try:
            # Deploy OpenCost service
            if not self.deploy_opencost_service(manifest_path):
                result['error'] = "Failed to deploy OpenCost service"
                return result

            # Wait for service to be ready
            if not self.wait_for_service_ready():
                result['error'] = "OpenCost service did not become ready"
                return result

            # Start port forwarding
            local_port = self.start_port_forward()
            if not local_port:
                result['error'] = "Failed to establish port-forward"
                return result

            # Generate output file names
            allocation_file = f"{self.cluster_context}_{run_id}_cost_allocation.json"
            assets_file = f"{self.cluster_context}_{run_id}_cost_assets.json"

            allocation_output = os.path.join(result_dir, allocation_file)
            assets_output = os.path.join(result_dir, assets_file)

            # Collect cost data
            success = self.collect_cost_data(
                window=window,
                aggregate=aggregate,
                scenario_name=scenario_name,
                run_id=run_id,
                metadata=metadata,
                allocation_output=allocation_output,
                assets_output=assets_output,
                local_port=local_port,
                validate_availability=validate_availability
            )

            if success:
                result['success'] = True
                result['allocation_file'] = allocation_file
                result['assets_file'] = assets_file
            else:
                result['error'] = "Cost data collection failed"

        except Exception as e:
            result['error'] = f"Collection process failed: {str(e)}"
            logger.error(f"Collection process failed: {str(e)}")

        finally:
            # Cleanup port-forward
            self.cleanup_port_forward()

        return result


def main():
    """Main function to run the cost collection process."""
    parser = argparse.ArgumentParser(description="Kubernetes Cost Analysis Collector")
    parser.add_argument("--cluster-context", required=True, help="Kubernetes cluster context")
    parser.add_argument("--manifest-path", required=True, help="Path to OpenCost service manifest")
    parser.add_argument("--window", required=True, help="Time window for data collection")
    parser.add_argument("--aggregate", default="container", help="Aggregation level")
    parser.add_argument("--scenario-name", required=True, help="Scenario name")
    parser.add_argument("--run-id", required=True, help="Run ID")
    parser.add_argument("--scenario-stage-name", help="Scenario stage name")
    parser.add_argument("--result-dir", required=True, help="Directory to save results")
    parser.add_argument("--validate-availability", action="store_true",
                       help="Validate data availability")

    args = parser.parse_args()

    # Prepare metadata
    metadata = {}
    if args.scenario_stage_name:
        metadata['scenario_stage_name'] = args.scenario_stage_name

    # Create collector instance
    collector = OpenCostKubernetesCollector(cluster_context=args.cluster_context)

    # Run collection
    result = collector.run_collection(
        manifest_path=args.manifest_path,
        window=args.window,
        aggregate=args.aggregate,
        scenario_name=args.scenario_name,
        run_id=args.run_id,
        metadata=metadata,
        result_dir=args.result_dir,
        validate_availability=args.validate_availability
    )

    # Output results for Azure DevOps pipeline
    if result['success']:
        print("Cost analysis collection completed successfully")
        sys.exit(0)
    else:
        print(f"Cost analysis collection failed: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
