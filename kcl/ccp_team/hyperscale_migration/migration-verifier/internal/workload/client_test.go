package workload

import (
	"context"
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

func smallConfig() Config {
	return Config{
		Seed: "test-seed", Namespace: "migration-test", Concurrency: 3,
		Specs: []IngestionSpec{
			{Kind: ConfigMapKind, Count: 2, PayloadBytes: 128},
			{Kind: SecretKind, Count: 2, PayloadBytes: 128},
			{Kind: PodKind, Count: 2, PayloadBytes: 128},
		},
	}
}

func TestIngestAndVerify(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	runner := NewRunner(client)
	manifest, err := runner.Ingest(ctx, smallConfig())
	if err != nil {
		t.Fatalf("Ingest() error = %v", err)
	}
	if len(manifest.Objects) != 6 {
		t.Fatalf("object count = %d, want 6", len(manifest.Objects))
	}

	if err := runner.Verify(ctx, manifest); err != nil {
		t.Fatalf("Verify() error = %v", err)
	}
}

func TestVerifyDetectsPayloadCorruption(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	runner := NewRunner(client)
	manifest, err := runner.Ingest(ctx, Config{
		Seed: "seed", Namespace: "ns", Concurrency: 1,
		Specs: []IngestionSpec{{Kind: ConfigMapKind, Count: 1, PayloadBytes: 32}},
	})
	if err != nil {
		t.Fatal(err)
	}
	configMap, err := client.CoreV1().ConfigMaps("ns").Get(ctx, "migration-configmap-000000", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	configMap.BinaryData[payloadKey][0]++
	if _, err := client.CoreV1().ConfigMaps("ns").Update(ctx, configMap, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := runner.Verify(ctx, manifest); err == nil || !strings.Contains(err.Error(), "hash mismatch") {
		t.Fatalf("Verify() error = %v, want hash mismatch", err)
	}
}

func TestVerifyDetectsPodPayloadCorruption(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	runner := NewRunner(client)
	manifest, err := runner.Ingest(ctx, Config{
		Seed: "seed", Namespace: "ns", Concurrency: 1,
		Specs: []IngestionSpec{{Kind: PodKind, Count: 1, PayloadBytes: 32}},
	})
	if err != nil {
		t.Fatal(err)
	}
	pod, err := client.CoreV1().Pods("ns").Get(ctx, "migration-pod-000000-pod", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	pod.Annotations[payloadAnnotation] = "Y29ycnVwdGVk"
	if _, err := client.CoreV1().Pods("ns").Update(ctx, pod, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := runner.Verify(ctx, manifest); err == nil || !strings.Contains(err.Error(), "hash mismatch") {
		t.Fatalf("Verify() error = %v, want hash mismatch", err)
	}
}

func TestVerifyDetectsDeploymentDrift(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	runner := NewRunner(client)
	manifest, err := runner.Ingest(ctx, Config{
		Seed: "seed", Namespace: "ns", Concurrency: 1,
		Specs: []IngestionSpec{{Kind: PodKind, Count: 1, PayloadBytes: 32}},
	})
	if err != nil {
		t.Fatal(err)
	}
	deployment, err := client.AppsV1().Deployments("ns").Get(ctx, "migration-pod-000000", metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	deployment.Spec.Template.Spec.Containers[0].Image = "unexpected:latest"
	if _, err := client.AppsV1().Deployments("ns").Update(ctx, deployment, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := runner.Verify(ctx, manifest); err == nil || !strings.Contains(err.Error(), "structural hash mismatch") {
		t.Fatalf("Verify() error = %v, want structural hash mismatch", err)
	}
}

func TestValidateConfigRejectsOversizedPodAnnotation(t *testing.T) {
	config := smallConfig()
	config.Specs = []IngestionSpec{{Kind: PodKind, Count: 1, PayloadBytes: 200 * 1024}}
	if err := ValidateConfig(config); err == nil {
		t.Fatal("ValidateConfig() accepted an oversized Pod annotation")
	}
}

func TestWatchPodsReadyTracksAllPods(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	client := fake.NewClientset()
	ready, err := NewRunner(client).watchPodsReady(ctx, "ns", 2)
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"first", "second"} {
		pod := &corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: "ns", Labels: map[string]string{migrationLabel: "true"}}}
		if _, err := client.CoreV1().Pods("ns").Create(ctx, pod, metav1.CreateOptions{}); err != nil {
			t.Fatal(err)
		}
	}
	select {
	case err := <-ready:
		t.Fatalf("watch completed before Pods were ready: %v", err)
	default:
	}
	for _, name := range []string{"first", "second"} {
		pod, err := client.CoreV1().Pods("ns").Get(ctx, name, metav1.GetOptions{})
		if err != nil {
			t.Fatal(err)
		}
		pod.Status.Phase = corev1.PodRunning
		pod.Status.Conditions = []corev1.PodCondition{{Type: corev1.PodReady, Status: corev1.ConditionTrue}}
		if _, err := client.CoreV1().Pods("ns").UpdateStatus(ctx, pod, metav1.UpdateOptions{}); err != nil {
			t.Fatal(err)
		}
	}
	if err := <-ready; err != nil {
		t.Fatal(err)
	}
}

func newFakeClientWithPodController() *fake.Clientset {
	client := fake.NewClientset()
	client.PrependReactor("create", "deployments", func(action k8stesting.Action) (bool, runtime.Object, error) {
		deployment := action.(k8stesting.CreateAction).GetObject().(*appsv1.Deployment).DeepCopy()
		deployment.Status.AvailableReplicas = 1
		if err := client.Tracker().Create(appsv1.SchemeGroupVersion.WithResource("deployments"), deployment, deployment.Namespace); err != nil {
			return true, nil, err
		}
		pod := readyPod(*deployment)
		if err := client.Tracker().Create(corev1.SchemeGroupVersion.WithResource("pods"), pod, pod.Namespace); err != nil {
			return true, nil, err
		}
		return true, deployment, nil
	})
	return client
}

func readyPod(deployment appsv1.Deployment) *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:        deployment.Name + "-pod",
			Namespace:   deployment.Namespace,
			Labels:      deployment.Spec.Template.Labels,
			Annotations: deployment.Spec.Template.Annotations,
		},
		Status: corev1.PodStatus{
			Phase:      corev1.PodRunning,
			Conditions: []corev1.PodCondition{{Type: corev1.PodReady, Status: corev1.ConditionTrue}},
		},
	}
}
