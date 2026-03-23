import azure_pipelines.ap.steps
import lib.steps.azure

RunClusterLoader2Local = lambda serviceConnection: str, cl2Image: str, overrideContent: str, testConfig: str = "testing/load/config.yaml", provider: str = "aks", extraArgs: str = "" -> steps.Step {
    script = """
if ! command -v docker &>/dev/null; then
  echo "##[error]Docker is not installed on this agent. Please use an agent pool with Docker pre-installed."
  exit 1
fi
echo "Docker found: $(docker --version)"

mkdir -p /tmp/cl2-config /tmp/cl2-results

cat > /tmp/cl2-config/overrides.yaml << 'OVERRIDE_EOF'
${overrideContent}
OVERRIDE_EOF

echo "=== CL2 Override Config ==="
cat /tmp/cl2-config/overrides.yaml
echo "==========================="

set +e
docker run --rm \
  --network host \
  -v "$HOME/.kube/config:/root/.kube/config:rw" \
  -v "$HOME/.azure:/root/.azure:rw" \
  -v "/tmp/cl2-config:/root/perf-tests/clusterloader2/config:rw" \
  -v "/tmp/cl2-results:/root/perf-tests/clusterloader2/results:rw" \
  ${cl2Image} \
  --provider=${provider} \
  --v=2 \
  --testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml \
  --testconfig=${testConfig} \
  --kubeconfig=/root/.kube/config \
  --report-dir=/root/perf-tests/clusterloader2/results \
  ${extraArgs}
CL2_EXIT=$?
set -e

echo "=== CL2 Results ==="
ls -la /tmp/cl2-results/

if [ $CL2_EXIT -ne 0 ]; then
  echo "##[warning]CL2 exited with code $CL2_EXIT (test failures), but continuing pipeline."
fi
"""
    azure.AzCli(serviceConnection, "Run CL2 locally on agent", script)
}
