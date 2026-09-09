package workload

import "time"

// IngestionSpec defines the object count and payload size for one Kubernetes resource kind.
type IngestionSpec struct {
	Kind         string `json:"kind"`
	Count        int    `json:"count"`
	PayloadBytes int    `json:"payloadBytes"`
}

// ObjectRecord captures an ingested object's identity and expected hashes for post-migration verification.
type ObjectRecord struct {
	Kind           string `json:"kind"`
	Namespace      string `json:"namespace"`
	Name           string `json:"name"`
	PayloadHash    string `json:"payloadHash"`
	StructuralHash string `json:"structuralHash,omitempty"`
}

// Manifest records an ingestion run and is persisted as the expected state for post-migration verification.
type Manifest struct {
	Version             int             `json:"version"`
	Seed                string          `json:"seed"`
	CreatedAt           time.Time       `json:"createdAt"`
	LogicalPayloadBytes int64           `json:"logicalPayloadBytes"`
	Specs               []IngestionSpec `json:"specs"`
	Objects             []ObjectRecord  `json:"objects"`
}

type Config struct {
	Seed        string
	Namespace   string
	Concurrency int
	Specs       []IngestionSpec
}

func DefaultConfig() Config {
	return Config{
		Seed:        DefaultSeed,
		Namespace:   DefaultNamespace,
		Concurrency: DefaultConcurrency,
		Specs:       DefaultSpecs(),
	}
}

func DefaultSpecs() []IngestionSpec {
	return []IngestionSpec{
		{Kind: ConfigMapKind, Count: DefaultConfigMapCount, PayloadBytes: DefaultConfigMapPayloadBytes},
		{Kind: SecretKind, Count: DefaultSecretCount, PayloadBytes: DefaultSecretPayloadBytes},
		{Kind: PodKind, Count: DefaultPodCount, PayloadBytes: DefaultPodPayloadBytes},
	}
}

func TotalPayloadBytes(specs []IngestionSpec) int64 {
	var total int64
	for _, spec := range specs {
		total += int64(spec.Count) * int64(spec.PayloadBytes)
	}
	return total
}
