package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

const (
	defaultProbeTimeout  = 60 * time.Second
	defaultProbeInterval = 2 * time.Second
	defaultHTTPTimeout   = 3 * time.Second
)

func main() {
	// Record start timestamp
	startTs := time.Now().UTC()
	log.Printf("Start timestamp: %s", startTs.Format("2006-01-02T15:04:05.000Z07:00"))

	// Get pod info from downward API
	podName := mustEnv("MY_POD_NAME")
	podNamespace := mustEnv("MY_POD_NAMESPACE")
	probeTarget := mustEnv("PROBE_TARGET")

	// Optional configuration
	probeTimeout := getEnvDuration("PROBE_TIMEOUT", defaultProbeTimeout)
	probeInterval := getEnvDuration("PROBE_INTERVAL", defaultProbeInterval)

	log.Printf("Starting reporter: %s/%s", podNamespace, podName)
	log.Printf("Probe target: %s, timeout: %v, interval: %v", probeTarget, probeTimeout, probeInterval)

	// Check if annotations already exist (idempotency)
	cfg, err := rest.InClusterConfig()
	if err != nil {
		log.Fatalf("Failed to get in-cluster config: %v", err)
	}

	clientset, err := kubernetes.NewForConfig(cfg)
	if err != nil {
		log.Fatalf("Failed to create kubernetes client: %v", err)
	}

	// Check existing annotations
	pod, err := clientset.CoreV1().Pods(podNamespace).Get(context.TODO(), podName, metav1.GetOptions{})
	if err != nil {
		log.Fatalf("Failed to get pod: %v", err)
	}

	hasStartTs := false
	if pod.Annotations != nil {
		if _, hasStart := pod.Annotations["perf.github.com/azure-start-ts"]; hasStart {
			hasStartTs = true
			if _, hasDp := pod.Annotations["perf.github.com/azure-dp-ready-ts"]; hasDp {
				log.Println("Annotations already present, skipping patch (idempotent)")
				return
			}
		}
	}

	// Probe until success
	dpReadyTs := probeUntilSuccess(probeTarget, probeTimeout, probeInterval)

	if dpReadyTs.IsZero() {
		log.Printf("Warning: Datapath probe did not succeed within timeout %v", probeTimeout)
	} else {
		log.Printf("Datapath ready timestamp: %s (latency: %v)", dpReadyTs.Format("2006-01-02T15:04:05.000Z07:00"), dpReadyTs.Sub(startTs))
	}

	// Patch pod annotations
	if err := patchPodAnnotations(clientset, podNamespace, podName, startTs, dpReadyTs, hasStartTs); err != nil {
		log.Fatalf("Failed to patch pod annotations: %v", err)
	}

	log.Println("Successfully patched pod annotations")
}

// probeUntilSuccess attempts to probe the target until success or timeout
func probeUntilSuccess(target string, timeout, interval time.Duration) time.Time {
	deadline := time.Now().Add(timeout)
	attempt := 0

	for time.Now().Before(deadline) {
		attempt++
		if probe(target) {
			readyTs := time.Now().UTC()
			log.Printf("Probe succeeded on attempt %d", attempt)
			return readyTs
		}
		log.Printf("Probe attempt %d failed, retrying in %v", attempt, interval)
		time.Sleep(interval)
	}

	log.Printf("Probe timeout after %d attempts", attempt)
	return time.Time{}
}

// probe attempts to reach the target via HTTP or TCP
func probe(target string) bool {
	parsedURL, err := url.Parse(target)
	if err != nil {
		log.Printf("Invalid probe target URL: %v", err)
		return false
	}

	switch parsedURL.Scheme {
	case "http", "https":
		return probeHTTP(target)
	case "tcp":
		return probeTCP(parsedURL.Host)
	default:
		// Default to TCP if no scheme
		return probeTCP(target)
	}
}

// probeHTTP performs an HTTP GET request
func probeHTTP(target string) bool {
	client := &http.Client{
		Timeout: defaultHTTPTimeout,
	}

	resp, err := client.Get(target)
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	return resp.StatusCode >= 200 && resp.StatusCode < 400
}

// probeTCP performs a TCP dial
func probeTCP(address string) bool {
	conn, err := net.DialTimeout("tcp", address, defaultHTTPTimeout)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

// patchPodAnnotations patches the pod with start and datapath ready timestamps
func patchPodAnnotations(clientset *kubernetes.Clientset, namespace, name string, startTs, dpReadyTs time.Time, hasStartTs bool) error {
	annotations := map[string]string{}

	if !hasStartTs {
		annotations["perf.github.com/azure-start-ts"] = startTs.Format("2006-01-02T15:04:05.000Z07:00")
	}

	if !dpReadyTs.IsZero() {
		annotations["perf.github.com/azure-dp-ready-ts"] = dpReadyTs.Format("2006-01-02T15:04:05.000Z07:00")
	}

	patch := map[string]interface{}{
		"metadata": map[string]interface{}{
			"annotations": annotations,
		},
	}

	patchBytes, err := json.Marshal(patch)
	if err != nil {
		return fmt.Errorf("failed to marshal patch: %w", err)
	}

	_, err = clientset.CoreV1().Pods(namespace).Patch(
		context.TODO(),
		name,
		types.MergePatchType,
		patchBytes,
		metav1.PatchOptions{},
	)
	if err != nil {
		return fmt.Errorf("failed to patch pod: %w", err)
	}

	return nil
}

// mustEnv gets an environment variable or exits
func mustEnv(key string) string {
	value := os.Getenv(key)
	if value == "" {
		log.Fatalf("Missing required environment variable: %s", key)
	}
	return value
}

// getEnvDuration gets a duration from environment variable or returns default
func getEnvDuration(key string, defaultValue time.Duration) time.Duration {
	value := os.Getenv(key)
	if value == "" {
		return defaultValue
	}

	seconds, err := strconv.Atoi(value)
	if err != nil {
		log.Printf("Invalid duration value for %s: %v, using default %v", key, err, defaultValue)
		return defaultValue
	}

	return time.Duration(seconds) * time.Second
}
