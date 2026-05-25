import azure_pipelines.ap.steps

InstallRunkperf = lambda runnerImage: str -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

temp_dir=$(mktemp -p /tmp -d kperfinstall.XXXX)
docker rmi ${runnerImage} 2>/dev/null || true
docker pull ${runnerImage}
docker run --rm -v $temp_dir:/install-dir \\
  ${runnerImage} bash -c "set -x; install /kperf /runkperf /install-dir"

sudo install $temp_dir/kperf $temp_dir/runkperf /usr/local/bin
rm -rf $temp_dir
docker rmi ${runnerImage} 2>/dev/null || true
"""
        displayName = "Install runkperf binary"
    }
}
