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
	maxRetries           = 10
	initialRetryDelay    = 100 * time.Millisecond
)

func main() {
	// Record start timestamp
	startTs := time.Now().UTC()
	log.Printf("Start timestamp: %s", startTs.Format(time.RFC3339Nano))

	// Get pod info from downward API
	podName := mustEnv("MY_POD_NAME")
	podNamespace := mustEnv("MY_POD_NAMESPACE")
	probeTarget := mustEnv("PROBE_TARGET")

	// Optional configuration
	probeTimeout := getEnvDuration("PROBE_TIMEOUT", defaultProbeTimeout)
	probeInterval := getEnvDuration("PROBE_INTERVAL", defaultProbeInterval)

	log.Printf("Starting reporter: %s/%s", podNamespace, podName)
	log.Printf("Probe target: %s, timeout: %v, interval: %v", probeTarget, probeTimeout, probeInterval)

	// Start probing immediately in background to avoid K8s API overhead in datapath latency measurement
	probeResultCh := make(chan time.Time, 1)
	go func() {
		dpReadyTs := probeUntilSuccess(probeTarget, probeTimeout, probeInterval)
		probeResultCh <- dpReadyTs
	}()

	// Create Kubernetes client in parallel (with retries)
	clientset, err := createClientsetWithRetry()
	if err != nil {
		log.Fatalf("Failed to create kubernetes client after retries: %v", err)
	}

	// Check existing annotations (with retries)
	pod, err := getPodWithRetry(clientset, podNamespace, podName)
	if err != nil {
		log.Fatalf("Failed to get pod after retries: %v", err)
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

	// Wait for probe result
	dpReadyTs := <-probeResultCh

	if dpReadyTs.IsZero() {
		log.Fatalf("Datapath probe did not succeed within timeout %v, failing to trigger retry", probeTimeout)
	}

	log.Printf("Datapath ready timestamp: %s (latency: %v)", dpReadyTs.Format(time.RFC3339Nano), dpReadyTs.Sub(startTs))

	// Patch pod annotations (with retries)
	if err := patchPodAnnotationsWithRetry(clientset, podNamespace, podName, startTs, dpReadyTs, hasStartTs); err != nil {
		log.Fatalf("Failed to patch pod annotations after retries: %v", err)
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

// createClientsetWithRetry creates a Kubernetes clientset with retry logic
func createClientsetWithRetry() (*kubernetes.Clientset, error) {
	var clientset *kubernetes.Clientset
	var lastErr error

	for attempt := 0; attempt < maxRetries; attempt++ {
		cfg, err := rest.InClusterConfig()
		if err != nil {
			lastErr = fmt.Errorf("failed to get in-cluster config: %w", err)
			if attempt < maxRetries-1 {
				delay := initialRetryDelay * (1 << uint(attempt))
				log.Printf("Failed to get in-cluster config (attempt %d/%d): %v, retrying in %v", attempt+1, maxRetries, err, delay)
				time.Sleep(delay)
				continue
			}
			break
		}

		clientset, err = kubernetes.NewForConfig(cfg)
		if err == nil {
			return clientset, nil
		}

		lastErr = fmt.Errorf("failed to create clientset: %w", err)
		if attempt < maxRetries-1 {
			delay := initialRetryDelay * (1 << uint(attempt))
			log.Printf("Failed to create kubernetes client (attempt %d/%d): %v, retrying in %v", attempt+1, maxRetries, err, delay)
			time.Sleep(delay)
		}
	}

	return clientset, fmt.Errorf("failed after %d attempts: %w", maxRetries, lastErr)
}

// getPodWithRetry gets a pod with exponential backoff retry logic
func getPodWithRetry(clientset *kubernetes.Clientset, namespace, name string) (*metav1.ObjectMeta, error) {
	var pod *metav1.ObjectMeta
	var lastErr error

	for attempt := 0; attempt < maxRetries; attempt++ {
		p, err := clientset.CoreV1().Pods(namespace).Get(context.TODO(), name, metav1.GetOptions{})
		if err == nil {
			return &p.ObjectMeta, nil
		}

		lastErr = err
		if attempt < maxRetries-1 {
			delay := initialRetryDelay * (1 << uint(attempt)) // Exponential backoff
			log.Printf("Failed to get pod (attempt %d/%d): %v, retrying in %v", attempt+1, maxRetries, err, delay)
			time.Sleep(delay)
		}
	}

	return pod, fmt.Errorf("failed after %d attempts: %w", maxRetries, lastErr)
}

// patchPodAnnotationsWithRetry patches pod annotations with retry logic
func patchPodAnnotationsWithRetry(clientset *kubernetes.Clientset, namespace, name string, startTs, dpReadyTs time.Time, hasStartTs bool) error {
	var lastErr error

	for attempt := 0; attempt < maxRetries; attempt++ {
		err := patchPodAnnotations(clientset, namespace, name, startTs, dpReadyTs, hasStartTs)
		if err == nil {
			return nil
		}

		lastErr = err
		if attempt < maxRetries-1 {
			delay := initialRetryDelay * (1 << uint(attempt)) // Exponential backoff
			log.Printf("Failed to patch pod (attempt %d/%d): %v, retrying in %v", attempt+1, maxRetries, err, delay)
			time.Sleep(delay)
		}
	}

	return fmt.Errorf("failed after %d attempts: %w", maxRetries, lastErr)
}

// patchPodAnnotations patches the pod with start and datapath ready timestamps
func patchPodAnnotations(clientset *kubernetes.Clientset, namespace, name string, startTs, dpReadyTs time.Time, hasStartTs bool) error {
	annotations := map[string]string{}

	if !hasStartTs {
		annotations["perf.github.com/azure-start-ts"] = startTs.Format(time.RFC3339Nano)
	}

	if !dpReadyTs.IsZero() {
		annotations["perf.github.com/azure-dp-ready-ts"] = dpReadyTs.Format(time.RFC3339Nano)
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
