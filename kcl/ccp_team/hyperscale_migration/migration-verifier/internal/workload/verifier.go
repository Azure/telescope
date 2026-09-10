package workload

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

type Verifier struct {
	client kubernetes.Interface
}

func NewVerifier(client kubernetes.Interface) *Verifier {
	return &Verifier{client: client}
}

func (verifier *Verifier) Verify(ctx context.Context, manifest Manifest) error {
	if len(manifest.Objects) == 0 {
		return errors.New("manifest contains no objects")
	}
	expected := make(map[string]ObjectRecord, len(manifest.Objects))
	for _, record := range manifest.Objects {
		expected[record.Kind+"/"+record.Name] = record
	}
	actual := map[string]bool{}
	namespace := manifest.Objects[0].Namespace

	if err := verifier.verifyConfigMaps(ctx, namespace, expected, actual); err != nil {
		return err
	}
	if err := verifier.verifySecrets(ctx, namespace, expected, actual); err != nil {
		return err
	}
	if err := verifier.verifyPods(ctx, namespace, expected, actual); err != nil {
		return err
	}
	if len(actual) != len(expected) {
		return fmt.Errorf("verified %d objects, expected %d", len(actual), len(expected))
	}
	return nil
}

func (verifier *Verifier) verifyConfigMaps(ctx context.Context, namespace string, expected map[string]ObjectRecord, actual map[string]bool) error {
	listConfigMaps := func(options metav1.ListOptions) ([]corev1.ConfigMap, string, error) {
		configMaps, err := verifier.client.CoreV1().ConfigMaps(namespace).List(ctx, options)
		if err != nil {
			return nil, "", fmt.Errorf("list configmaps: %w", err)
		}
		return configMaps.Items, configMaps.Continue, nil
	}
	verifyConfigMap := func(object corev1.ConfigMap) error {
		return verifyPayload(expected, actual, ConfigMapKind, object.Name, object.BinaryData[payloadKey])
	}
	return pageListAndVerify(listConfigMaps, verifyConfigMap)
}

func (verifier *Verifier) verifySecrets(ctx context.Context, namespace string, expected map[string]ObjectRecord, actual map[string]bool) error {
	listSecrets := func(options metav1.ListOptions) ([]corev1.Secret, string, error) {
		secrets, err := verifier.client.CoreV1().Secrets(namespace).List(ctx, options)
		if err != nil {
			return nil, "", fmt.Errorf("list secrets: %w", err)
		}
		return secrets.Items, secrets.Continue, nil
	}
	verifySecret := func(object corev1.Secret) error {
		return verifyPayload(expected, actual, SecretKind, object.Name, object.Data[payloadKey])
	}
	return pageListAndVerify(listSecrets, verifySecret)
}

func (verifier *Verifier) verifyPods(ctx context.Context, namespace string, expected map[string]ObjectRecord, actual map[string]bool) error {
	listPods := func(options metav1.ListOptions) ([]corev1.Pod, string, error) {
		pods, err := verifier.client.CoreV1().Pods(namespace).List(ctx, options)
		if err != nil {
			return nil, "", fmt.Errorf("list pods: %w", err)
		}
		return pods.Items, pods.Continue, nil
	}
	verifyPod := func(pod corev1.Pod) error {
		payload, decodeErr := base64.StdEncoding.DecodeString(pod.Annotations[payloadAnnotation])
		if decodeErr != nil {
			return fmt.Errorf("decode Pod/%s payload: %w", pod.Name, decodeErr)
		}
		return verifyPayload(expected, actual, PodKind, pod.Name, payload)
	}
	return pageListAndVerify(listPods, verifyPod)
}

// pageListAndVerify paginates migration objects to avoid one large List response and processes each item without accumulating all results.
func pageListAndVerify[T any](list func(metav1.ListOptions) ([]T, string, error), process func(T) error) error {
	options := metav1.ListOptions{LabelSelector: migrationLabelSelector, Limit: DefaultVerifyPageSize}
	for {
		items, continueToken, err := list(options)
		if err != nil {
			return err
		}
		for _, item := range items {
			if err := process(item); err != nil {
				return err
			}
		}
		if continueToken == "" {
			return nil
		}
		options.Continue = continueToken
	}
}

func verifyPayload(expected map[string]ObjectRecord, actual map[string]bool, kind, name string, payload []byte) error {
	key := kind + "/" + name
	record, found := expected[key]
	if !found {
		return fmt.Errorf("unexpected object %s", key)
	}
	if got := computeHash(payload); got != record.PayloadHash {
		return fmt.Errorf("payload hash mismatch for %s: got %s, want %s", key, got, record.PayloadHash)
	}
	actual[key] = true
	return nil
}
