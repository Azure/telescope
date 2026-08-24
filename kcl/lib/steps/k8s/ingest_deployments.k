import azure_pipelines.ap.steps

# Constants for deployment/pod ingestion
REPLICAS_PER_DEPLOYMENT = 100
POD_MANIFEST_SIZE_BYTES = 10240  # 10 KiB per pod (via annotation padding)
GIB_BYTES = 1073741824

# RunDeploymentIngest creates Deployments where each deployment has
# REPLICAS_PER_DEPLOYMENT pods and each pod carries a single annotation with a
# random payload of POD_MANIFEST_SIZE_BYTES bytes. Annotations have no
# per-value length limit (unlike labels, which cap values at 63 chars).
# The number of deployments is: totalGiB * GiB / POD_MANIFEST_SIZE_BYTES / REPLICAS_PER_DEPLOYMENT.
RunDeploymentIngest = lambda namespace: str, name: str, totalGiB: str -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

TOTAL_POD_BYTES=$(( ${totalGiB} * ${GIB_BYTES} ))
TOTAL_PODS=$(( TOTAL_POD_BYTES / ${POD_MANIFEST_SIZE_BYTES} ))
NUM_DEPLOYMENTS=$(( TOTAL_PODS / ${REPLICAS_PER_DEPLOYMENT} ))

if [ "$NUM_DEPLOYMENTS" -le 0 ]; then
  echo "Requested totalGiB=${totalGiB} yields 0 deployments; skipping."
  exit 0
fi

kubectl create namespace ${namespace} 2>/dev/null || true

# Generate a random string exactly ${POD_MANIFEST_SIZE_BYTES} bytes long,
# used as a single annotation value on every pod.
RANDOM_STR=$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c ${POD_MANIFEST_SIZE_BYTES})

echo "Creating $NUM_DEPLOYMENTS deployments (${REPLICAS_PER_DEPLOYMENT} replicas each, ~${POD_MANIFEST_SIZE_BYTES}B/pod) in namespace ${namespace}..."

TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

for i in $(seq 1 $NUM_DEPLOYMENTS); do
  cat >> "$TMPFILE" <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${name}-$i
  namespace: ${namespace}
spec:
  replicas: ${REPLICAS_PER_DEPLOYMENT}
  selector:
    matchLabels:
      app: ${name}-$i
  template:
    metadata:
      labels:
        app: ${name}-$i
      annotations:
        pad: "\${RANDOM_STR}"
    spec:
      terminationGracePeriodSeconds: 0
      containers:
      - name: pause
        image: mcr.microsoft.com/oss/kubernetes/pause:3.6
        resources:
          requests:
            cpu: 1m
            memory: 1Mi
---
EOF

  # Apply in batches of 50 deployments to avoid oversized single apply calls.
  if [ $(( i % 50 )) -eq 0 ] || [ "$i" -eq "$NUM_DEPLOYMENTS" ]; then
    kubectl apply -f "$TMPFILE" --server-side=true
    : > "$TMPFILE"
    echo "Progress: $i / $NUM_DEPLOYMENTS deployments applied"
  fi
done

echo "Deployment ingest complete: $NUM_DEPLOYMENTS deployments, ~$TOTAL_PODS pods."
"""
        displayName = "Ingest deployments (${totalGiB} GiB of pod manifests)"
        condition = "and(succeeded(), ne('${totalGiB}', '0'))"
    }
}
