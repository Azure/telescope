package workload

import (
	"context"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

func TestIngestAndVerify(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	manifest, err := NewIngestor(client).Ingest(ctx, smallConfig())
	if err != nil {
		t.Fatalf("Ingest() error = %v", err)
	}
	if len(manifest.Objects) != 6 {
		t.Fatalf("object count = %d, want 6", len(manifest.Objects))
	}
	if err := NewVerifier(client).Verify(ctx, manifest); err != nil {
		t.Fatalf("Verify() error = %v", err)
	}
}

func TestVerifyDetectsPayloadCorruption(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	manifest, err := NewIngestor(client).Ingest(ctx, Config{
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
	if err := NewVerifier(client).Verify(ctx, manifest); err == nil || !strings.Contains(err.Error(), "hash mismatch") {
		t.Fatalf("Verify() error = %v, want hash mismatch", err)
	}
}

func TestVerifyPaginatesConfigMaps(t *testing.T) {
	ctx := context.Background()
	client := fake.NewClientset()
	payloads := [][]byte{[]byte("first"), []byte("second")}
	manifest := Manifest{Objects: []ObjectRecord{
		{Kind: ConfigMapKind, Namespace: "ns", Name: "first", PayloadHash: computeHash(payloads[0])},
		{Kind: ConfigMapKind, Namespace: "ns", Name: "second", PayloadHash: computeHash(payloads[1])},
	}}
	listCalls := 0
	client.PrependReactor("list", "configmaps", func(action k8stesting.Action) (bool, runtime.Object, error) {
		listCalls++
		options := action.(interface{ GetListOptions() metav1.ListOptions }).GetListOptions()
		if options.Limit != DefaultVerifyPageSize {
			t.Fatalf("list limit = %d, want %d", options.Limit, DefaultVerifyPageSize)
		}
		switch options.Continue {
		case "":
			return true, &corev1.ConfigMapList{
				ListMeta: metav1.ListMeta{Continue: "next"},
				Items: []corev1.ConfigMap{{
					ObjectMeta: metav1.ObjectMeta{Name: "first", Labels: map[string]string{migrationLabel: "true"}},
					BinaryData: map[string][]byte{payloadKey: payloads[0]},
				}},
			}, nil
		case "next":
			return true, &corev1.ConfigMapList{
				Items: []corev1.ConfigMap{{
					ObjectMeta: metav1.ObjectMeta{Name: "second", Labels: map[string]string{migrationLabel: "true"}},
					BinaryData: map[string][]byte{payloadKey: payloads[1]},
				}},
			}, nil
		default:
			t.Fatalf("unexpected continue token %q", options.Continue)
			return true, nil, nil
		}
	})
	if err := NewVerifier(client).Verify(ctx, manifest); err != nil {
		t.Fatal(err)
	}
	if listCalls != 2 {
		t.Fatalf("configmap list calls = %d, want 2", listCalls)
	}
}

func TestVerifyDetectsPodPayloadCorruption(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	manifest, err := NewIngestor(client).Ingest(ctx, Config{
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
	if err := NewVerifier(client).Verify(ctx, manifest); err == nil || !strings.Contains(err.Error(), "hash mismatch") {
		t.Fatalf("Verify() error = %v, want hash mismatch", err)
	}
}

func TestVerifyDetectsUnreadyPod(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	manifest, err := NewIngestor(client).Ingest(ctx, Config{
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
	pod.Status.Conditions = nil
	if _, err := client.CoreV1().Pods("ns").UpdateStatus(ctx, pod, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := NewVerifier(client).Verify(ctx, manifest); err == nil || !strings.Contains(err.Error(), "not Running and Ready") {
		t.Fatalf("Verify() error = %v, want Pod readiness error", err)
	}
}

func TestVerifyDetectsDeploymentDrift(t *testing.T) {
	ctx := context.Background()
	client := newFakeClientWithPodController()
	manifest, err := NewIngestor(client).Ingest(ctx, Config{
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
	if err := NewVerifier(client).Verify(ctx, manifest); err == nil || !strings.Contains(err.Error(), "structural hash mismatch") {
		t.Fatalf("Verify() error = %v, want structural hash mismatch", err)
	}
}
