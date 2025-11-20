coredns_log() {
    coredns_pods=$(kubectl get pods -n kube-system -l k8s-app=kube-dns -o jsonpath='{.items[*].metadata.name}')
    for pod in $coredns_pods; do
        echo "Collecting CoreDNS logs from pod: $pod"
        kubectl logs -n kube-system "$pod" > "$pod.txt"
        cat "$pod.txt" | grep "NXDOMAIN" > "${pod}_nxdomain.txt"
    done
}

service_log() {
    service_number=$1
    namespace=$2
    service_pods=$(kubectl get pods -n "$namespace" -l service=test-service-${service_number} -o jsonpath='{.items[*].metadata.name}')
    for pod in $service_pods; do
        echo "Collecting logs from service pod: $pod in namespace: $namespace"
        kubectl logs -n "$namespace" "$pod" -c dns-checker > "${namespace}_${pod}.txt"
    done
}

service_log 20 "testns"