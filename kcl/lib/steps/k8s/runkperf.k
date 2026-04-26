import azure_pipelines.ap.steps

# Default constants for kperf data ingestion
DEFAULT_QPS = 80
DEFAULT_BURST = 80
DEFAULT_SIZE = 524288  # 0.5MB per object
DEFAULT_GROUP_SIZE = 80
DEFAULT_BATCH_SIZE = 2000  # Internal batch size, not configurable by caller

InstallRunkperf = lambda runnerImage: str, condition: str = None -> steps.Step {
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
        condition = condition
    }
}

# RunKperfDataIngest creates objects in fixed-size batches (DEFAULT_BATCH_SIZE) to be
# resilient to failures — if a batch fails, only that batch needs to be retried, and the
# local in-memory counter stays accurate since each successful batch represents a known
# quantity. This avoids using kubectl get to count existing objects, which would OOM
# the pipeline agent by fetching full object bodies.
RunKperfDataIngest = lambda dataType: str, namespace: str, name: str, total: str | int, displayName: str = None, qps: int = DEFAULT_QPS, burst: int = DEFAULT_BURST, size: int = DEFAULT_SIZE, groupSize: int = DEFAULT_GROUP_SIZE, condition: str = None -> steps.Step {
    _batchSize = DEFAULT_BATCH_SIZE
    _displayName = displayName or "Ingest ${dataType} data"
    steps.Script {
        script = """
set -euo pipefail
set -x

TARGET=${total}
BATCH_SIZE=${_batchSize}

kubectl create namespace ${namespace} 2>/dev/null || true

TOTAL_BATCHES=$(( (TARGET + BATCH_SIZE - 1) / BATCH_SIZE ))
echo "Ingesting $TARGET ${dataType}s in $TOTAL_BATCHES batches of $BATCH_SIZE..."

completed=0
for batch in $(seq 1 $TOTAL_BATCHES); do
  REMAINING=$((TARGET - completed))
  COUNT=$BATCH_SIZE
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
  run_batch x || run_batch retry

  completed=$((completed + COUNT))
  STORAGE_GIB=$(awk 'BEGIN{printf "%.1f", '$completed' * ${size} / 1073741824}')
  echo "Progress: $completed / $TARGET ${dataType}s created (~$STORAGE_GIB GiB)"
done

echo "Ingest complete: $completed ${dataType}s created."
"""
        displayName = _displayName
        condition = condition
    }
}
