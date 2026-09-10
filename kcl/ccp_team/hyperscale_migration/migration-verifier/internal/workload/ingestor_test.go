package workload

import (
	"context"
	"errors"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
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

func TestValidateConfigRejectsOversizedPodAnnotation(t *testing.T) {
	config := smallConfig()
	config.Specs = []IngestionSpec{{Kind: PodKind, Count: 1, PayloadBytes: 200 * 1024}}
	if err := ValidateConfig(config); err == nil {
		t.Fatal("ValidateConfig() accepted an oversized Pod annotation")
	}
}

func TestCreateObjectRetriesThreeTimes(t *testing.T) {
	ctx := context.Background()
	client := fake.NewClientset()
	attempts := 0
	client.PrependReactor("create", "configmaps", func(action k8stesting.Action) (bool, runtime.Object, error) {
		attempts++
		if attempts < DefaultCreateAttempts {
			return true, nil, errors.New("transient connection error")
		}
		return false, nil, nil
	})
	ingestor := NewIngestor(client)
	ingestor.createRetryInterval = 0

	manifest, err := ingestor.Ingest(ctx, Config{
		Seed: "seed", Namespace: "ns", Concurrency: 1,
		Specs: []IngestionSpec{{Kind: ConfigMapKind, Count: 1, PayloadBytes: 32}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if attempts != DefaultCreateAttempts {
		t.Fatalf("create attempts = %d, want %d", attempts, DefaultCreateAttempts)
	}
	if len(manifest.Objects) != 1 {
		t.Fatalf("manifest objects = %d, want 1", len(manifest.Objects))
	}
}

func TestCreateObjectRecoversAlreadyExistsAfterAmbiguousCreate(t *testing.T) {
	ctx := context.Background()
	client := fake.NewClientset()
	attempts := 0
	client.PrependReactor("create", "configmaps", func(action k8stesting.Action) (bool, runtime.Object, error) {
		attempts++
		if attempts == 2 {
			return true, nil, apierrors.NewAlreadyExists(corev1.Resource("configmaps"), "migration-configmap-000000")
		}
		object := action.(k8stesting.CreateAction).GetObject().(*corev1.ConfigMap).DeepCopy()
		object.Namespace = action.GetNamespace()
		if err := client.Tracker().Create(corev1.SchemeGroupVersion.WithResource("configmaps"), object, object.Namespace); err != nil {
			return true, nil, err
		}
		return true, nil, errors.New("http2: server sent GOAWAY")
	})
	ingestor := NewIngestor(client)
	ingestor.createRetryInterval = 0

	manifest, err := ingestor.Ingest(ctx, Config{
		Seed: "seed", Namespace: "ns", Concurrency: 1,
		Specs: []IngestionSpec{{Kind: ConfigMapKind, Count: 1, PayloadBytes: 32}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if attempts != 2 {
		t.Fatalf("create attempts = %d, want 2", attempts)
	}
	if len(manifest.Objects) != 1 {
		t.Fatalf("manifest objects = %d, want 1", len(manifest.Objects))
	}
}

func TestCreateObjectRejectsMismatchedObjectAfterAmbiguousCreate(t *testing.T) {
	ctx := context.Background()
	client := fake.NewClientset()
	attempts := 0
	client.PrependReactor("create", "configmaps", func(action k8stesting.Action) (bool, runtime.Object, error) {
		attempts++
		if attempts == 2 {
			return true, nil, apierrors.NewAlreadyExists(corev1.Resource("configmaps"), "migration-configmap-000000")
		}
		object := action.(k8stesting.CreateAction).GetObject().(*corev1.ConfigMap).DeepCopy()
		object.Namespace = action.GetNamespace()
		object.BinaryData[payloadKey] = []byte("mismatched")
		if err := client.Tracker().Create(corev1.SchemeGroupVersion.WithResource("configmaps"), object, object.Namespace); err != nil {
			return true, nil, err
		}
		return true, nil, errors.New("http2: server sent GOAWAY")
	})
	ingestor := NewIngestor(client)
	ingestor.createRetryInterval = 0

	_, err := ingestor.Ingest(ctx, Config{
		Seed: "seed", Namespace: "ns", Concurrency: 1,
		Specs: []IngestionSpec{{Kind: ConfigMapKind, Count: 1, PayloadBytes: 32}},
	})
	if err == nil || !strings.Contains(err.Error(), "payload hash mismatch") {
		t.Fatalf("Ingest() error = %v, want payload hash mismatch", err)
	}
}
