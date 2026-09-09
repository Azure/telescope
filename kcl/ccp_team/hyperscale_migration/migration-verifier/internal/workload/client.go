package workload

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"sort"
	"sync"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/apimachinery/pkg/watch"
	"k8s.io/client-go/kubernetes"
)

type Runner struct {
	client              kubernetes.Interface
	createRetryInterval time.Duration
}

func NewRunner(client kubernetes.Interface) *Runner {
	return &Runner{client: client, createRetryInterval: DefaultCreateRetryInterval}
}

func ValidateConfig(config Config) error {
	if config.Namespace == "" || config.Seed == "" {
		return errors.New("namespace and seed must not be empty")
	}
	if config.Concurrency < 1 {
		return errors.New("concurrency must be at least 1")
	}
	seen := map[string]bool{}
	for _, spec := range config.Specs {
		if spec.Kind != ConfigMapKind && spec.Kind != SecretKind && spec.Kind != PodKind {
			return fmt.Errorf("unsupported kind %q", spec.Kind)
		}
		if seen[spec.Kind] {
			return fmt.Errorf("duplicate kind %q", spec.Kind)
		}
		seen[spec.Kind] = true
		if spec.Count < 0 || spec.PayloadBytes < 1 || spec.PayloadBytes > maxPayloadBytes {
			return fmt.Errorf("invalid %s count=%d payloadBytes=%d", spec.Kind, spec.Count, spec.PayloadBytes)
		}
		if spec.Kind == PodKind && base64.StdEncoding.EncodedLen(spec.PayloadBytes) > 240*1024 {
			return fmt.Errorf("pod payload %d exceeds safe annotation size", spec.PayloadBytes)
		}
	}
	return nil
}

func (runner *Runner) Ingest(ctx context.Context, config Config) (Manifest, error) {
	if err := ValidateConfig(config); err != nil {
		return Manifest{}, err
	}
	if err := runner.ensureNamespace(ctx, config.Namespace); err != nil {
		return Manifest{}, err
	}

	manifest := Manifest{
		Version:             1,
		Seed:                config.Seed,
		CreatedAt:           time.Now().UTC(),
		LogicalPayloadBytes: TotalPayloadBytes(config.Specs),
		Specs:               config.Specs,
	}
	type task struct {
		spec  IngestionSpec
		index int
	}
	tasks := make(chan task)
	records := make(chan ObjectRecord)
	errCh := make(chan error, 1)
	workerCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	podsReady, err := runner.watchPodsReady(workerCtx, config.Namespace, expectedPodCount(config.Specs))
	if err != nil {
		return manifest, err
	}

	var workers sync.WaitGroup
	for range config.Concurrency {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for item := range tasks {
				record, err := runner.createObject(workerCtx, config, item.spec, item.index)
				if err != nil {
					select {
					case errCh <- err:
						cancel()
					default:
					}
					return
				}
				select {
				case records <- record:
				case <-workerCtx.Done():
					return
				}
			}
		}()
	}
	go func() {
		defer close(tasks)
		for _, spec := range config.Specs {
			for index := range spec.Count {
				select {
				case tasks <- task{spec: spec, index: index}:
				case <-workerCtx.Done():
					return
				}
			}
		}
	}()
	go func() {
		workers.Wait()
		close(records)
	}()

	for record := range records {
		manifest.Objects = append(manifest.Objects, record)
	}
	sort.Slice(manifest.Objects, func(i, j int) bool {
		if manifest.Objects[i].Kind == manifest.Objects[j].Kind {
			return manifest.Objects[i].Name < manifest.Objects[j].Name
		}
		return manifest.Objects[i].Kind < manifest.Objects[j].Kind
	})
	select {
	case err := <-errCh:
		return manifest, err
	default:
	}
	if err := <-podsReady; err != nil {
		return manifest, err
	}
	return manifest, nil
}

func expectedPodCount(specs []IngestionSpec) int {
	for _, spec := range specs {
		if spec.Kind == PodKind {
			return spec.Count
		}
	}
	return 0
}

func (runner *Runner) watchPodsReady(ctx context.Context, namespace string, expected int) (<-chan error, error) {
	result := make(chan error, 1)
	if expected == 0 {
		result <- nil
		return result, nil
	}
	selector := labels.Set{migrationLabel: "true"}.AsSelector().String()
	watchCtx, cancel := context.WithTimeout(ctx, DefaultPodReadyTimeout)
	podWatch, err := runner.client.CoreV1().Pods(namespace).Watch(watchCtx, metav1.ListOptions{LabelSelector: selector})
	if err != nil {
		cancel()
		return nil, fmt.Errorf("watch pods: %w", err)
	}
	go func() {
		defer cancel()
		defer podWatch.Stop()
		states := make(map[string]bool, expected)
		for {
			select {
			case <-watchCtx.Done():
				result <- fmt.Errorf("wait for %d pods to become ready: %w", expected, watchCtx.Err())
				return
			case event, open := <-podWatch.ResultChan():
				if !open {
					result <- fmt.Errorf("pod watch closed before %d pods became ready", expected)
					return
				}
				if event.Type == watch.Error {
					result <- apierrors.FromObject(event.Object)
					return
				}
				pod, ok := event.Object.(*corev1.Pod)
				if !ok {
					result <- fmt.Errorf("pod watch returned %T", event.Object)
					return
				}
				if event.Type == watch.Deleted {
					delete(states, pod.Name)
				} else {
					states[pod.Name] = pod.Status.Phase == corev1.PodRunning && isPodReady(*pod)
				}
				if len(states) == expected {
					allReady := true
					for _, ready := range states {
						allReady = allReady && ready
					}
					if allReady {
						result <- nil
						return
					}
				}
			}
		}
	}()
	return result, nil
}

func (runner *Runner) ensureNamespace(ctx context.Context, namespace string) error {
	_, err := runner.client.CoreV1().Namespaces().Create(ctx, &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: namespace}}, metav1.CreateOptions{})
	if err != nil && !apierrors.IsAlreadyExists(err) {
		return fmt.Errorf("create namespace %s: %w", namespace, err)
	}
	return nil
}

func (runner *Runner) createObject(ctx context.Context, config Config, spec IngestionSpec, index int) (ObjectRecord, error) {
	record, create, err := runner.prepareObject(ctx, config, spec, index)
	if err != nil {
		return ObjectRecord{}, err
	}

	for attempt := 1; ; attempt++ {
		err = create()
		if err == nil {
			return record, nil
		}
		if apierrors.IsAlreadyExists(err) {
			return ObjectRecord{}, fmt.Errorf("create %s %s: %w", spec.Kind, record.Name, err)
		}

		if attempt >= DefaultCreateAttempts {
			return ObjectRecord{}, fmt.Errorf("create %s %s after %d attempts: %w", spec.Kind, record.Name, DefaultCreateAttempts, err)
		}

		delay := runner.createRetryInterval * time.Duration(1<<(attempt-1))
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ObjectRecord{}, ctx.Err()
		case <-timer.C:
		}
	}
}

func (runner *Runner) prepareObject(ctx context.Context, config Config, spec IngestionSpec, index int) (ObjectRecord, func() error, error) {
	payload := createPayload(config.Seed, spec.Kind, index, spec.PayloadBytes)
	name := formatObjectName(spec.Kind, index)
	objectLabels := map[string]string{migrationLabel: "true"}
	record := ObjectRecord{Kind: spec.Kind, Namespace: config.Namespace, Name: name, PayloadHash: computeHash(payload)}
	var create func() error
	switch spec.Kind {
	case ConfigMapKind:
		object := &corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{Name: name, Labels: objectLabels},
			BinaryData: map[string][]byte{payloadKey: payload},
		}
		create = func() error {
			_, err := runner.client.CoreV1().ConfigMaps(config.Namespace).Create(ctx, object, metav1.CreateOptions{})
			return err
		}
	case SecretKind:
		object := &corev1.Secret{
			ObjectMeta: metav1.ObjectMeta{Name: name, Labels: objectLabels},
			Data:       map[string][]byte{payloadKey: payload},
		}
		create = func() error {
			_, err := runner.client.CoreV1().Secrets(config.Namespace).Create(ctx, object, metav1.CreateOptions{})
			return err
		}
	case PodKind:
		deployment := newDeployment(config.Namespace, name, objectLabels, payload)
		record.StructuralHash = computeDeploymentHash(deployment)
		create = func() error {
			_, err := runner.client.AppsV1().Deployments(config.Namespace).Create(ctx, deployment, metav1.CreateOptions{})
			return err
		}
	default:
		return ObjectRecord{}, nil, fmt.Errorf("unsupported kind %q", spec.Kind)
	}
	return record, create, nil
}

func newDeployment(namespace, name string, objectLabels map[string]string, payload []byte) *appsv1.Deployment {
	replicas := int32(1)
	podLabels := map[string]string{"app": name, migrationLabel: "true"}
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Namespace: namespace,
			Name:      name,
			Labels:    objectLabels,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: map[string]string{"app": name}},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      podLabels,
					Annotations: map[string]string{payloadAnnotation: base64.StdEncoding.EncodeToString(payload)},
				},
				Spec: corev1.PodSpec{
					NodeSelector: map[string]string{"type": "kwok"},
					Tolerations:  []corev1.Toleration{{Key: "kubernetes.io/arch", Operator: corev1.TolerationOpEqual, Value: "arm64", Effect: corev1.TaintEffectNoSchedule}},
					Containers:   []corev1.Container{{Name: "pause", Image: "mcr.microsoft.com/oss/kubernetes/pause:3.9"}},
				},
			},
		},
	}
}

func (runner *Runner) Verify(ctx context.Context, manifest Manifest) error {
	if len(manifest.Objects) == 0 {
		return errors.New("manifest contains no objects")
	}
	expected := make(map[string]ObjectRecord, len(manifest.Objects))
	for _, record := range manifest.Objects {
		expected[record.Kind+"/"+record.Name] = record
	}
	actual := map[string]bool{}
	selector := labels.Set{migrationLabel: "true"}.AsSelector().String()
	namespace := manifest.Objects[0].Namespace

	configMaps, err := runner.client.CoreV1().ConfigMaps(namespace).List(ctx, metav1.ListOptions{LabelSelector: selector})
	if err != nil {
		return fmt.Errorf("list configmaps: %w", err)
	}
	for _, object := range configMaps.Items {
		if err := verifyPayload(expected, actual, ConfigMapKind, object.Name, object.BinaryData[payloadKey]); err != nil {
			return err
		}
	}

	secrets, err := runner.client.CoreV1().Secrets(namespace).List(ctx, metav1.ListOptions{LabelSelector: selector})
	if err != nil {
		return fmt.Errorf("list secrets: %w", err)
	}
	for _, object := range secrets.Items {
		if err := verifyPayload(expected, actual, SecretKind, object.Name, object.Data[payloadKey]); err != nil {
			return err
		}
	}
	deployments, err := runner.client.AppsV1().Deployments(namespace).List(ctx, metav1.ListOptions{LabelSelector: selector})
	if err != nil {
		return fmt.Errorf("list deployments: %w", err)
	}
	for _, object := range deployments.Items {
		record, found := expected[PodKind+"/"+object.Name]
		if !found {
			return fmt.Errorf("unexpected Deployment/%s", object.Name)
		}
		if got := computeDeploymentHash(&object); got != record.StructuralHash {
			return fmt.Errorf("structural hash mismatch for Deployment/%s: got %s, want %s", object.Name, got, record.StructuralHash)
		}
		if object.Status.AvailableReplicas != 1 {
			return fmt.Errorf("Deployment/%s available replicas = %d, want 1", object.Name, object.Status.AvailableReplicas)
		}
	}
	if err := runner.verifyPods(ctx, namespace, deployments.Items, expected, actual); err != nil {
		return err
	}
	if len(actual) != len(expected) {
		return fmt.Errorf("verified %d objects, expected %d", len(actual), len(expected))
	}
	return nil
}

func (runner *Runner) verifyPods(ctx context.Context, namespace string, deployments []appsv1.Deployment, expected map[string]ObjectRecord, actual map[string]bool) error {
	pods, err := runner.client.CoreV1().Pods(namespace).List(ctx, metav1.ListOptions{LabelSelector: labels.Set{migrationLabel: "true"}.AsSelector().String()})
	if err != nil {
		return fmt.Errorf("list pods: %w", err)
	}
	readyByApp := map[string]int{}
	for _, pod := range pods.Items {
		logicalName := pod.Labels["app"]
		payload, decodeErr := base64.StdEncoding.DecodeString(pod.Annotations[payloadAnnotation])
		if decodeErr != nil {
			return fmt.Errorf("decode Pod/%s payload: %w", pod.Name, decodeErr)
		}
		if err := verifyPayload(expected, actual, PodKind, logicalName, payload); err != nil {
			return err
		}
		if pod.Status.Phase != corev1.PodRunning || !isPodReady(pod) {
			continue
		}
		readyByApp[pod.Labels["app"]]++
	}
	for _, deployment := range deployments {
		if readyByApp[deployment.Name] != 1 {
			return fmt.Errorf("Deployment/%s ready pods = %d, want 1", deployment.Name, readyByApp[deployment.Name])
		}
	}
	return nil
}

func isPodReady(pod corev1.Pod) bool {
	for _, condition := range pod.Status.Conditions {
		if condition.Type == corev1.PodReady && condition.Status == corev1.ConditionTrue {
			return true
		}
	}
	return false
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
