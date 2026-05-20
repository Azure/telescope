import azure_pipelines.ap.steps

# Default constants for kperf data ingestion
DEFAULT_QPS = 80
DEFAULT_BURST = 80
DEFAULT_SIZE_BYTES = 524288  # 0.5 MiB per object
DEFAULT_GROUP_SIZE = 80
BATCH_SIZE = 2000  # Internal batch size, not configurable by caller
BYTES_PER_GIB = 1073741824

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

# RunKperfDataIngest creates objects in fixed-size batches (BATCH_SIZE) to be
# resilient to failures — if a batch fails, only that batch needs to be retried, and the
# local in-memory counter stays accurate since each successful batch represents a known
# quantity. This avoids using kubectl get to count existing objects, which would OOM
# the pipeline agent by fetching full object bodies.
RunKperfDataIngest = lambda dataType: str, namespace: str, name: str, totalGiB: str, qps: int = DEFAULT_QPS, burst: int = DEFAULT_BURST, size: int = DEFAULT_SIZE_BYTES, groupSize: int = DEFAULT_GROUP_SIZE -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

TOTAL_OBJECTS_COUNT=$(( ${totalGiB} * ${BYTES_PER_GIB} / ${size} ))
TOTAL_BATCHES=$(( (TOTAL_OBJECTS_COUNT + ${BATCH_SIZE} - 1) / ${BATCH_SIZE} ))

kubectl create namespace ${namespace} 2>/dev/null || true

echo "Ingesting $TOTAL_OBJECTS_COUNT ${dataType}s in $TOTAL_BATCHES batches of ${BATCH_SIZE}..."

completed=0
for batch in $(seq 1 $TOTAL_BATCHES); do
  REMAINING=$((TOTAL_OBJECTS_COUNT - completed))
  COUNT=${BATCH_SIZE}
  if [ "$REMAINING" -lt "$COUNT" ]; then
    COUNT=$REMAINING
  fi

  echo "Batch $batch/$TOTAL_BATCHES: creating $COUNT ${dataType}s..."
  run_batch() {
    runkperf data ${dataType} \\
      --namespace ${namespace} \\
      add ${name}-b$batch-$1 \\
      --qps ${qps} \\
      --burst ${burst} \\
      --total $COUNT \\
      --size ${size} \\
      --group-size ${groupSize}
  }
  run_batch first || run_batch retry

  completed=$((completed + COUNT))
  STORAGE_GIB=$(awk 'BEGIN{printf "%.1f", '$completed' * ${size} / ${BYTES_PER_GIB}}')
  echo "Progress: $completed / $TOTAL_OBJECTS_COUNT ${dataType}s created (~$STORAGE_GIB GiB)"
done

echo "Ingest complete: $completed ${dataType}s created."
"""
        displayName = "Ingest ${dataType} data (${totalGiB} GiB)"
        condition = "and(succeeded(), ne('${totalGiB}', '0'))"
    }
}

# RunKperfBenchmark runs runkperf bench with the given subcommand and flow control settings.
# Results are written to resultPath (default /tmp/tmp_results.json) for collection by CollectKperfResult.
RunKperfBenchmark = lambda runnerImage: str, flowcontrol: str, benchmark_subcmd: str, benchmark_subcmd_args: str, resultPath: str = "/tmp/tmp_results.json", target: str = None -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

# Install kubectl and ensure runkperf is in PATH
export PATH="/:$HOME/.local/bin:$PATH"
mkdir -p $HOME/.local/bin
ln -sf /runkperf $HOME/.local/bin/runkperf
ln -sf /kperf $HOME/.local/bin/kperf
curl -sLo $HOME/.local/bin/kubectl "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x $HOME/.local/bin/kubectl

/runkperf -v 3 bench \\
  --runner-image="${runnerImage}" \\
  --runner-flowcontrol="${flowcontrol}" \\
  --result ${resultPath} \\
  ${benchmark_subcmd} ${benchmark_subcmd_args}
"""
        displayName = "Run kperf benchmark (${benchmark_subcmd}, flowcontrol=${flowcontrol})"
        target = target
    }
}
