package workload

import "time"

const (
	ConfigMapKind = "ConfigMap"
	SecretKind    = "Secret"
	PodKind       = "Pod"

	migrationLabel         = "telescope.azure.com/hyperscale-migration"
	migrationLabelSelector = migrationLabel + "=true"
	payloadAnnotation      = "telescope.azure.com/payload"
	payloadKey             = "payload"
	maxPayloadBytes        = 512 * 1024

	DefaultNamespace                   = "hyperscale-migration"
	DefaultSeed                        = "hyperscale-migration-v1"
	DefaultConcurrency                 = 32
	DefaultQPS                 float32 = 80
	DefaultBurst                       = 160
	DefaultCreateAttempts              = 3
	DefaultCreateRetryInterval         = 2 * time.Second
	DefaultPodReadyTimeout             = 30 * time.Minute
	DefaultVerifyTimeout               = 30 * time.Minute
	DefaultVerifyPollInterval          = 30 * time.Second
	DefaultVerifyPageSize      int64   = 50

	// ConfigMaps and Secrets each contribute 250 MiB; Pods contribute 62.5 MiB:
	// Estimated baseline: 562.5 MiB total.
	DefaultConfigMapCount        = 1000
	DefaultConfigMapPayloadBytes = 256 * 1024
	DefaultSecretCount           = 1000
	DefaultSecretPayloadBytes    = 256 * 1024
	DefaultPodCount              = 2000
	DefaultPodPayloadBytes       = 32 * 1024
)
