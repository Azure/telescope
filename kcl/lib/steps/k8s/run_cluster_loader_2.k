import azure_pipelines.ap.steps
import lib.steps.azure

MAX_CONSECUTIVE_APISERVER_ERRORS = 20

# The manifest must identify exactly one Job by name and namespace.
RunClusterLoader2 = lambda serviceConnection: str, manifest: str -> steps.Step {
    script = """
set +eo pipefail
manifest_path="$(Pipeline.Workspace)/s/${manifest}"
job_details="$(kubectl create --dry-run=client --validate=false -f "$manifest_path" -o go-template='{{if eq .kind "Job"}}{{if .metadata.name}}{{.metadata.name}}{{end}} {{if .metadata.namespace}}{{.metadata.namespace}}{{end}}{{"\\n"}}{{end}}')" || exit 1
mapfile -t jobs < <(printf '%s' "$job_details")
if [ "\${#jobs[@]}" -ne 1 ]; then
  echo "Expected exactly one CL2 Job in $manifest_path, found \${#jobs[@]}" >&2
  exit 1
fi
read -r job_name namespace <<< "\${jobs[0]}"
if [ -z "$job_name" ] || [ -z "$namespace" ]; then
  echo "CL2 Job must have metadata.name and metadata.namespace" >&2
  exit 1
fi
kubectl create namespace "$namespace" || true
kubectl apply -f "$manifest_path" || exit 1
# Wait
consecutive_errors=0
while true; do
  # Under consistent API server errors, we would want to exit early instead of waiting for the entire timeout duration.
  conditions="$(kubectl get job "$job_name" --namespace="$namespace" -o jsonpath='{range .status.conditions[?(@.status=="True")]}{.type}{"\\n"}{end}' 2>/tmp/kubectl_err)"
  kubectl_exit_code=$?
  if [ $kubectl_exit_code -ne 0 ]; then
    consecutive_errors=$((consecutive_errors + 1))
    echo "kubectl get job $job_name failed (exit_code=$kubectl_exit_code, consecutive=$consecutive_errors/${MAX_CONSECUTIVE_APISERVER_ERRORS}):"
    cat /tmp/kubectl_err
    if [ "$consecutive_errors" -ge "${MAX_CONSECUTIVE_APISERVER_ERRORS}" ]; then
      echo "Unable to read CL2 Job $job_name for $consecutive_errors consecutive polls; aborting."
      exit 1
    fi
    sleep 30
    continue
  fi
  consecutive_errors=0

  while IFS= read -r condition; do
    case "$condition" in
      Failed)
        echo "CL2 Job $job_name failed"
        kubectl get job "$job_name" --namespace="$namespace" -o yaml || echo "Unable to fetch CL2 Job $job_name failure details."
        exit 1
        ;;
      Complete)
        echo "CL2 Job $job_name completed successfully"
        exit 0
        ;;
    esac
  done <<< "$conditions"

  kubectl get pods --namespace="$namespace" -l "job-name=$job_name" -o wide || echo "Unable to list CL2 pods; retrying on the next poll."
  sleep 30
done
"""
    azure.AzCli(serviceConnection, "Run cluster loader 2", script)
}
