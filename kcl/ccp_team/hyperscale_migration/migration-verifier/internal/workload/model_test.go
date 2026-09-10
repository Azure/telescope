package workload

import "testing"

const expectedTotalPayloadBytes = 562*1024*1024 + 512*1024

func TestDefaultSpecsTotalExactly562Point5MiB(t *testing.T) {
	if got := TotalPayloadBytes(DefaultSpecs()); got != expectedTotalPayloadBytes {
		t.Fatalf("default payload total = %d, want %d", got, expectedTotalPayloadBytes)
	}
}

func TestPayloadIsDeterministicAndObjectSpecific(t *testing.T) {
	first := createPayload("seed", ConfigMapKind, 7, 1000)
	second := createPayload("seed", ConfigMapKind, 7, 1000)
	differentObject := createPayload("seed", ConfigMapKind, 8, 1000)
	differentKind := createPayload("seed", SecretKind, 7, 1000)

	if computeHash(first) != computeHash(second) {
		t.Fatal("identical inputs produced different payload hashes")
	}
	if computeHash(first) == computeHash(differentObject) {
		t.Fatal("different object indexes produced identical payload hashes")
	}
	if computeHash(first) == computeHash(differentKind) {
		t.Fatal("different kinds produced identical payload hashes")
	}
	if len(first) != 1000 {
		t.Fatalf("payload length = %d, want 1000", len(first))
	}
}

func TestObjectName(t *testing.T) {
	if got, want := formatObjectName(SecretKind, 42), "migration-secret-000042"; got != want {
		t.Fatalf("ObjectName() = %q, want %q", got, want)
	}
}
