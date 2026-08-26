import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

# Validate a CSI-backed StorageClass by creating a PVC, mounting it in a
# short-lived pod, and writing and reading a file. This validates provisioning
# and node mount behavior; validate the driver workloads separately.
ValidateCsiNode = lambda serviceConnection: str, storageClass: str, displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
  assert storageClass != "", "storageClass must be non-empty"
  title = displayName if displayName else "Validate CSI storage class ${storageClass}"
    script = """
set +e

suffix=$RANDOM
pvc="aks-validation-csi-pvc-$suffix"
pod="aks-validation-csi-pod-$suffix"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1; kubectl delete pvc "$pvc" --ignore-not-found >/dev/null 2>&1' EXIT

if ! kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ${storageClass}
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: $pod
spec:
  restartPolicy: Never
  containers:
    - name: writer
      image: ${const.BUSYBOX_IMAGE}
      command:
        - sh
        - -c
        - 'echo telescope-csi-check > /mnt/test/data && [ "$(cat /mnt/test/data)" = telescope-csi-check ]'
      volumeMounts:
        - name: vol
          mountPath: /mnt/test
  volumes:
    - name: vol
      persistentVolumeClaim:
        claimName: $pvc
EOF
then
  echo "FAILED CSI CHECK (${storageClass}): could not create test PVC or pod"
  exit 1
fi

# Wait for the pod to finish (Succeeded) or fail.
end=$((SECONDS + 300))
phase=""
while [ $SECONDS -lt $end ]; do
  phase=$(kubectl get pod "$pod" -o jsonpath='{.status.phase}' 2>/dev/null)
  [ "$phase" = "Succeeded" ] && break
  [ "$phase" = "Failed" ] && break
  sleep 5
done
echo "pod $pod phase=$phase"

if [ "$phase" != "Succeeded" ]; then
  echo "FAILED CSI CHECK (${storageClass}): pod did not succeed (phase=$phase); attach/mount likely failed"
  echo "--- pod describe ---"
  kubectl describe pod "$pod" | tail -30
  echo "--- pvc describe ---"
  kubectl describe pvc "$pvc" | tail -30
  echo "--- pod logs ---"
  kubectl logs "$pod" 2>&1
  exit 1
fi

echo "CSI storage class ${storageClass} validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
