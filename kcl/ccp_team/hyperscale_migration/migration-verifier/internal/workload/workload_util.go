package workload

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
)

type deploymentHashInput struct {
	Replicas       int32               `json:"replicas"`
	Selector       map[string]string   `json:"selector"`
	TemplateLabels map[string]string   `json:"templateLabels"`
	NodeSelector   map[string]string   `json:"nodeSelector"`
	Tolerations    []corev1.Toleration `json:"tolerations"`
	Containers     []corev1.Container  `json:"containers"`
}

// createPayload concatenates deterministic 32-byte SHA-256 digests, truncating the final digest to produce exactly size bytes.
func createPayload(seed, kind string, objectIndex, size int) []byte {
	if size <= 0 {
		return nil
	}

	payload := make([]byte, size)
	for blockIndex, offset := 0, 0; offset < size; blockIndex++ {
		// SHA-256 always produces a 32-byte digest.
		digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%d\x00%d", seed, kind, objectIndex, blockIndex)))
		offset += copy(payload[offset:], digest[:])
	}
	return payload
}

func computeHash(payload []byte) string {
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:])
}

func computeDeploymentHash(deployment *appsv1.Deployment) string {
	var replicas int32
	if deployment.Spec.Replicas != nil {
		replicas = *deployment.Spec.Replicas
	}
	structure := deploymentHashInput{
		Replicas:       replicas,
		Selector:       deployment.Spec.Selector.MatchLabels,
		TemplateLabels: deployment.Spec.Template.Labels,
		NodeSelector:   deployment.Spec.Template.Spec.NodeSelector,
		Tolerations:    deployment.Spec.Template.Spec.Tolerations,
		Containers:     deployment.Spec.Template.Spec.Containers,
	}
	contents, _ := json.Marshal(structure)
	return computeHash(contents)
}

func formatObjectName(kind string, objectIndex int) string {
	return fmt.Sprintf("migration-%s-%06d", strings.ToLower(kind), objectIndex)
}

func isPodReady(pod corev1.Pod) bool {
	for _, condition := range pod.Status.Conditions {
		if condition.Type == corev1.PodReady && condition.Status == corev1.ConditionTrue {
			return true
		}
	}
	return false
}
