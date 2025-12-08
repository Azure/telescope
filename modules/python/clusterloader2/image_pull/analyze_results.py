"""Analyze ClusterLoader2 image-pull test results."""

import json
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def _load_json(results_dir: str, pattern: str) -> dict:
    """Load most recent JSON matching pattern."""
    files = sorted(Path(results_dir).glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
    return json.load(open(files[0])) if files else {}


def _print(data: list, cols: list = None):
    """Print data as table."""
    if not data:
        return
    if HAS_PANDAS:
        df = pd.DataFrame(data)
        print(df.to_string(index=False) if not cols else df[cols].to_string(index=False))
    else:
        for row in data:
            print("  " + ", ".join(f"{k}={v}" for k, v in row.items()))


def analyze_results(results_dir: str) -> dict:
    """Analyze test results and return metrics."""
    results = Path(results_dir)
    if not results.exists():
        raise FileNotFoundError(f"Not found: {results_dir}")
    
    print(f"\n{'='*60}")
    print(f"Results: {results_dir}")
    print('='*60)
    
    # Pod startup latency
    data = _load_json(results_dir, "PodStartupLatency_*.json")
    if items := data.get('dataItems'):
        print("\nPod Startup Latency:")
        _print([{
            'Metric': i['labels']['Metric'],
            'P50': f"{i['data']['Perc50']:.0f}ms",
            'P90': f"{i['data']['Perc90']:.0f}ms",
            'P99': f"{i['data']['Perc99']:.0f}ms"
        } for i in items])
    
    # Image pull throughput
    data = _load_json(results_dir, "*ContainerdCriImagePullingThroughput_*.json")
    if items := data.get('dataItems'):
        print("\nImage Pulling Throughput:")
        for i in items:
            d = i.get('data', {})
            if s := d.get('Sum'):
                print(f"  {s:.2f} {i.get('unit', '')} total ({d.get('Count', 0)} pulls)")
    
    # Kubelet image pull duration
    data = _load_json(results_dir, "*KubeletRuntimeOperationDurationWithPullImage_*.json")
    if items := data.get('dataItems'):
        print("\nKubelet Image Pull Duration (per node):")
        nodes = [{
            'Node': i['labels']['node'][-8:],  # Last 8 chars of node name
            'P50': f"{i['data']['Perc50']:.1f}s",
            'P90': f"{i['data']['Perc90']:.1f}s",
            'P99': f"{i['data']['Perc99']:.1f}s"
        } for i in items if i.get('labels', {}).get('node') and 'Perc50' in i.get('data', {})]
        _print(nodes)
    
    # Test status
    junit = results / 'junit.xml'
    if junit.exists():
        tree = ET.parse(junit)
        failures = int(tree.getroot().get('failures', 0))
        errors = int(tree.getroot().get('errors', 0))
        status = 'PASS' if failures == 0 and errors == 0 else 'FAIL'
        print(f"\nTest Status: {status}")
    
    print('='*60)
    return {'status': status if junit.exists() else 'unknown'}


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: analyze_results.py <results_dir>")
        sys.exit(1)
    
    try:
        result = analyze_results(sys.argv[1])
        sys.exit(0 if result.get('status') == 'PASS' else 1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
