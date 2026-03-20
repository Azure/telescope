import azure_pipelines.ap.steps

InstallRunkperf = lambda runnerImage: str -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

temp_dir=$(mktemp -p /tmp -d kperfinstall.XXXX)
docker pull ${runnerImage}
docker run --rm -v $temp_dir:/install-dir \\
  ${runnerImage} bash -c "set -x; install /kperf /runkperf /install-dir"

sudo install $temp_dir/kperf $temp_dir/runkperf /usr/local/bin
rm -rf $temp_dir
docker rmi ${runnerImage}
"""
        displayName = "Install runkperf binary"
    }
}

RunKperfDataIngest = lambda namespace: str, qps: int, burst: int, name: str, total: int, size: int, groupSize: int -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

runkperf data configmap \\
  --namespace ${namespace} \\
  add ${name} \\
  --qps ${qps} \\
  --burst ${burst} \\
  --total ${total} \\
  --size ${size} \\
  --group-size ${groupSize}
"""
        displayName = "Run kperf data configmap ingest"
    }
}
