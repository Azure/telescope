import azure_pipelines.ap.steps

# Default constants for kperf data ingestion
DEFAULT_QPS = 80
DEFAULT_BURST = 80
DEFAULT_SIZE_BYTES = 524288  # 0.5 MiB per object
DEFAULT_GROUP_SIZE = 80
MAX_ATTEMPTS = 2  # Attempts per batch before failing the step
BYTES_PER_GIB = 1073741824

# RunKperfDataIngest creates either `total` objects or enough objects to fill
# `totalGiB`, in fixed-size batches (`batchSize`). When both are set, `total`
# takes precedence.
#
# Batching is used to be
# resilient to failures — if a batch fails, only that batch needs to be retried, and the
# local in-memory counter stays accurate since each successful batch represents a known
# quantity. This avoids using kubectl get to count existing objects, which would OOM
# the pipeline agent by fetching full object bodies.
# Each batch uses the set name "<name>-b<batch>", so object names are predictable and
# kperf load profiles can target a batch by its prefix.
RunKperfDataIngest = lambda dataType: str, namespace: str, name: str, totalGiB: str = "0", qps: int = DEFAULT_QPS, burst: int = DEFAULT_BURST, size: int = DEFAULT_SIZE_BYTES, groupSize: int = DEFAULT_GROUP_SIZE, total: int = 0, batchSize: int = 2000 -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

TOTAL_OBJECTS_COUNT=${total}
if [ "$TOTAL_OBJECTS_COUNT" -eq 0 ]; then
  TOTAL_OBJECTS_COUNT=$(awk 'BEGIN{printf "%d", ${totalGiB} * ${BYTES_PER_GIB} / ${size}}')
fi
TOTAL_BATCHES=$(( (TOTAL_OBJECTS_COUNT + ${batchSize} - 1) / ${batchSize} ))

kubectl create namespace ${namespace} 2>/dev/null || true

echo "Ingesting $TOTAL_OBJECTS_COUNT ${dataType}s in $TOTAL_BATCHES batches of ${batchSize}..."

completed=0
for batch in $(seq 1 $TOTAL_BATCHES); do
  REMAINING=$((TOTAL_OBJECTS_COUNT - completed))
  COUNT=${batchSize}
  if [ "$REMAINING" -lt "$COUNT" ]; then
    COUNT=$REMAINING
  fi

  echo "Batch $batch/$TOTAL_BATCHES: creating $COUNT ${dataType}s..."
  run_batch() {
    runkperf data ${dataType} \\
      --namespace ${namespace} \\
      add ${name}-b$batch \\
      --qps ${qps} \\
      --burst ${burst} \\
      --total $COUNT \\
      --size ${size} \\
      --group-size ${groupSize}
  }

  # add is not idempotent, so clear the partial batch before each retry.
  for attempt in $(seq 1 ${MAX_ATTEMPTS}); do
    run_batch && break
    if [ "$attempt" -eq "${MAX_ATTEMPTS}" ]; then
      echo "Batch $batch failed after ${MAX_ATTEMPTS} attempts" >&2
      exit 1
    fi
    echo "Batch $batch attempt $attempt failed; cleaning up before retry..."
    # delete reconstructs names <set>-<0..total-1>, so total must cover the whole batch.
    runkperf data ${dataType} --namespace ${namespace} delete ${name}-b$batch --total $COUNT || true
  done

  completed=$((completed + COUNT))
  STORAGE_GIB=$(awk 'BEGIN{printf "%.1f", '$completed' * ${size} / ${BYTES_PER_GIB}}')
  echo "Progress: $completed / $TOTAL_OBJECTS_COUNT ${dataType}s created (~$STORAGE_GIB GiB)"
done

echo "Ingest complete: $completed ${dataType}s created."
"""
        displayName = "Ingest ${dataType} data"
        condition = "and(succeeded(), or(ne('${total}', '0'), ne('${totalGiB}', '0')))"
    }
}
