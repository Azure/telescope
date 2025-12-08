"""Run ClusterLoader2 image-pull test."""

import os
import sys
import shutil
import logging
from pathlib import Path


def _copy_files(src_files: list, src_dir: Path, dst_dir: Path) -> None:
    """Copy multiple files from src to dst directory."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in src_files:
        src = src_dir / f if isinstance(f, str) else f
        if src.exists():
            shutil.copy(src, dst_dir / src.name)
            print(f"  - {src.name}")


def setup_config_files(scenario_dir: Path, cl2_config_dir: Path, root_dir: Path) -> None:
    """Copy configuration files for the test."""
    print(f"Setting up config in {cl2_config_dir}...")
    
    # Copy scenario files
    _copy_files(['image-pull.yaml', 'deployment.yaml', 'containerd-measurements.yaml'],
                scenario_dir, cl2_config_dir)
    
    # Copy kubelet measurements from modules
    kubelet_src = root_dir / 'modules/python/clusterloader2/cri/config/kubelet-measurement.yaml'
    _copy_files([kubelet_src], root_dir, cl2_config_dir)


def run_cl2_test(
    kubeconfig: str,
    root_dir: str,
    scenario_name: str = 'image-pull-test',
    cl2_image: str = 'ghcr.io/azure/clusterloader2:v20250311',
    prometheus_memory: str = '2Gi',
    storage_provisioner: str = 'kubernetes.io/azure-disk',
    storage_volume_type: str = 'StandardSSD_LRS'
) -> bool:
    """Run ClusterLoader2 image-pull test."""
    try:
        from clusterloader2.utils import run_cl2_command
    except ImportError:
        print("Error: Could not import clusterloader2.utils")
        return False
    
    # Setup paths
    root_path = Path(root_dir)
    scenario_dir = root_path / 'scenarios/perf-eval' / scenario_name
    cl2_config_dir = scenario_dir / 'cl2-config'
    results_dir = scenario_dir / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler(results_dir / 'cl2.log', mode='w'), logging.StreamHandler()]
    )
    
    try:
        setup_config_files(scenario_dir, cl2_config_dir, root_path)
        
        print(f"\n{'='*60}")
        print(f"Starting ClusterLoader2 Test")
        print(f"Results: {results_dir}")
        print(f"{'='*60}\n")
        
        run_cl2_command(
            kubeconfig=kubeconfig,
            cl2_image=cl2_image,
            cl2_config_dir=str(cl2_config_dir),
            cl2_report_dir=str(results_dir),
            provider='aks',
            cl2_config_file='image-pull.yaml',
            enable_prometheus=True,
            scrape_kubelets=True,
            scrape_containerd=True,
            tear_down_prometheus=False,
            extra_flags=f"--prometheus-memory-request={prometheus_memory} "
                       f"--prometheus-storage-class-provisioner={storage_provisioner} "
                       f"--prometheus-storage-class-volume-type={storage_volume_type}"
        )
        
        print(f"\nTest completed - Results in: {results_dir}")
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run ClusterLoader2 image-pull test')
    parser.add_argument('--kubeconfig', default=os.path.expanduser('~/.kube/config'))
    parser.add_argument('--root-dir', default=os.environ.get('ROOT_DIR', os.getcwd()))
    parser.add_argument('--scenario', default='image-pull-test')
    parser.add_argument('--cl2-image', default='ghcr.io/azure/clusterloader2:v20250311')
    parser.add_argument('--prometheus-memory', default='2Gi')
    parser.add_argument('--storage-provisioner', default='kubernetes.io/azure-disk')
    parser.add_argument('--storage-volume-type', default='StandardSSD_LRS')
    
    args = parser.parse_args()
    sys.path.insert(0, os.path.join(args.root_dir, 'modules/python'))
    
    success = run_cl2_test(
        kubeconfig=args.kubeconfig,
        root_dir=args.root_dir,
        scenario_name=args.scenario,
        cl2_image=args.cl2_image,
        prometheus_memory=args.prometheus_memory,
        storage_provisioner=args.storage_provisioner,
        storage_volume_type=args.storage_volume_type
    )
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
