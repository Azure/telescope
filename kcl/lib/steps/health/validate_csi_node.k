import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

# csi-azuredisk-node / csi-azurefile-node: create a PVC (disk or file), mount
# it in a short-lived pod, write+read a file to prove attach/mount/RW works,
# then delete the pod and PVC. For daemonset/pod health, pair with
# ValidateWorkloadHealth(kind="daemonset", name="csi-azure${driver}-node", namespace="kube-system").
#
# Both drivers use ReadWriteOnce for this single-pod mount check.
# driver="disk" -> default storageClass "managed-csi"
# driver="file" -> default storageClass "azurefile-csi"
ValidateCsiNode = lambda serviceConnection: str, driver: "disk" | "file", storageClass: str = "", displayName: str = "", continueOnError: bool = Undefined -> steps.Step {
    sc = storageClass if storageClass else ("managed-csi" if driver == "disk" else "azurefile-csi")
    title = displayName if displayName else "Validate csi-azure${driver}-node"
    script = """
set +e

suffix=$RANDOM
pvc="aks-validation-csi-${driver}-pvc-$suffix"
pod="aks-validation-csi-${driver}-pod-$suffix"
trap 'kubectl delete pod "$pod" --ignore-not-found >/dev/null 2>&1; kubectl delete pvc "$pvc" --ignore-not-found >/dev/null 2>&1' EXIT

if ! kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ${sc}
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
  echo "FAILED CSI-${driver} CHECK: could not create test PVC or pod"
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
  echo "FAILED CSI-${driver} CHECK: pod did not succeed (phase=$phase); attach/mount likely failed"
  echo "--- pod describe ---"
  kubectl describe pod "$pod" | tail -30
  echo "--- pvc describe ---"
  kubectl describe pvc "$pvc" | tail -30
  echo "--- pod logs ---"
  kubectl logs "$pod" 2>&1
  exit 1
fi

echo "csi-azure${driver}-node validation passed"
"""
    azure.AzCli(serviceConnection, title, script, continueOnError=continueOnError)
}
