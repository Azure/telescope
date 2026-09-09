package workload

import "time"

const (
	ConfigMapKind = "ConfigMap"
	SecretKind    = "Secret"
	PodKind       = "Pod"

	migrationLabel    = "telescope.azure.com/hyperscale-migration"
	payloadAnnotation = "telescope.azure.com/payload"
	payloadKey        = "payload"
	maxPayloadBytes   = 512 * 1024

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

	// ConfigMaps total 682.75 MiB
	// Secrets total 682.75 MiB
	// Pods total 682.5 MiB: exactly 2 GiB.
	DefaultConfigMapCount        = 2731
	DefaultConfigMapPayloadBytes = 256 * 1024
	DefaultSecretCount           = 2731
	DefaultSecretPayloadBytes    = 256 * 1024
	DefaultPodCount              = 5460
	DefaultPodPayloadBytes       = 128 * 1024
)
