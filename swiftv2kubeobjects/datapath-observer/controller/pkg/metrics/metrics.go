package metrics

import (
	"context"
	"sort"
	"strings"

	corev1 "k8s.io/api/core/v1"
	perfv1 "github.com/Azure/datapath-observer/controller/api/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type AggregatedResult struct {
	Metric          string      `json:"metric"`
	Unit            string      `json:"unit"`
	Count           int         `json:"count"`
	TotalSuccessful int         `json:"totalSuccessful"`
	TotalFailed     int         `json:"totalFailed"`
	P50             int64       `json:"p50"`
	P90             int64       `json:"p90"`
	P99             int64       `json:"p99"`
	WorstPods       []WorstPod  `json:"worstPods"`
	FailedPods      []FailedPod `json:"failedPods"`
}

type WorstPod struct {
	Namespace  string `json:"namespace"`
	Name       string `json:"name"`
	UID        string `json:"uid"`
	NodeName   string `json:"nodeName,omitempty"`
	CreatedAt  string `json:"createdAt,omitempty"`
	MeasuredTs string `json:"measuredTs,omitempty"`
	Value      int64  `json:"value"`
}

type FailedPod struct {
	Namespace string `json:"namespace"`
	Name      string `json:"name"`
	UID       string `json:"uid"`
	NodeName  string `json:"nodeName,omitempty"`
}

type PodHealthResult struct {
	Namespace       string       `json:"namespace"`
	LabelSelector   string       `json:"labelSelector,omitempty"`
	DesiredReplicas int          `json:"desiredReplicas"`
	RunningPods     int          `json:"runningPods"`
	PendingPods     int          `json:"pendingPods"`
	FailedPods      int          `json:"failedPods"`
	SuccessPct      float64      `json:"successPct"`
	PendingPodList  []PodDetails `json:"pendingPodList"`
	FailedPodList   []PodDetails `json:"failedPodList"`
}

type PodDetails struct {
	Namespace string `json:"namespace"`
	Name      string `json:"name"`
	UID       string `json:"uid"`
	NodeName  string `json:"nodeName,omitempty"`
	Phase     string `json:"phase"`
	Reason    string `json:"reason,omitempty"`
	Message   string `json:"message,omitempty"`
}

type MetricsCalculator struct {
	Client client.Client
}

func (m *MetricsCalculator) GetTimeToStart(ctx context.Context, namespace string, labels map[string]string, topN int) (*AggregatedResult, error) {
	return m.calculate(ctx, namespace, labels, topN, "time-to-start",
		func(d perfv1.DatapathResult) int64 {
			return d.Spec.Metrics.LatStartMs
		},
		func(d perfv1.DatapathResult) bool {
			return d.Spec.Timestamps.StartTs != ""
		},
		func(d perfv1.DatapathResult) string {
			return d.Spec.Timestamps.StartTs
		})
}

func (m *MetricsCalculator) GetTimeToDatapathReady(ctx context.Context, namespace string, labels map[string]string, topN int) (*AggregatedResult, error) {
	return m.calculate(ctx, namespace, labels, topN, "time-to-datapath-ready",
		func(d perfv1.DatapathResult) int64 {
			return d.Spec.Metrics.LatDpReadyMs
		},
		func(d perfv1.DatapathResult) bool {
			return d.Spec.Timestamps.DpReadyTs != ""
		},
		func(d perfv1.DatapathResult) string {
			return d.Spec.Timestamps.DpReadyTs
		})
}

func (m *MetricsCalculator) calculate(ctx context.Context, namespace string, labels map[string]string, topN int, metricName string, valueExtractor func(perfv1.DatapathResult) int64, successChecker func(perfv1.DatapathResult) bool, timestampExtractor func(perfv1.DatapathResult) string) (*AggregatedResult, error) {
	var list perfv1.DatapathResultList
	opts := []client.ListOption{}
	if namespace != "" {
		opts = append(opts, client.InNamespace(namespace))
	}
	if len(labels) > 0 {
		opts = append(opts, client.MatchingLabels(labels))
	}

	if err := m.Client.List(ctx, &list, opts...); err != nil {
		return nil, err
	}

	values := []int64{}
	worstPods := []WorstPod{}
	failedPods := []FailedPod{}
	totalSuccessful := 0
	totalFailed := 0

	for _, item := range list.Items {
		val := valueExtractor(item)
		hasTimestamp := successChecker(item)

		// Success = has timestamp AND non-zero latency (successful measurement)
		if hasTimestamp && val > 0 {
			totalSuccessful++
			values = append(values, val)
			worstPods = append(worstPods, WorstPod{
				Namespace:  item.Spec.PodRef.Namespace,
				Name:       item.Spec.PodRef.Name,
				UID:        item.Spec.PodRef.UID,
				NodeName:   item.Spec.PodRef.NodeName,
				CreatedAt:  item.Spec.Timestamps.CreatedAt,
				MeasuredTs: timestampExtractor(item),
				Value:      val,
			})
		} else {
			// Failed = missing timestamp OR zero latency
			totalFailed++
			failedPods = append(failedPods, FailedPod{
				Namespace: item.Spec.PodRef.Namespace,
				Name:      item.Spec.PodRef.Name,
				UID:       item.Spec.PodRef.UID,
				NodeName:  item.Spec.PodRef.NodeName,
			})
		}
	}

	count := len(values)

	// Limit failed pods to topN
	if len(failedPods) > topN {
		failedPods = failedPods[:topN]
	}

	if count == 0 {
		return &AggregatedResult{
			Metric:          metricName,
			Unit:            "ms",
			Count:           0,
			TotalSuccessful: totalSuccessful,
			TotalFailed:     totalFailed,
			FailedPods:      failedPods,
		}, nil
	}

	sort.Slice(values, func(i, j int) bool { return values[i] < values[j] })

	// Sort worstPods descending
	sort.Slice(worstPods, func(i, j int) bool { return worstPods[i].Value > worstPods[j].Value })
	if len(worstPods) > topN {
		worstPods = worstPods[:topN]
	}

	return &AggregatedResult{
		Metric:          metricName,
		Unit:            "ms",
		Count:           count,
		TotalSuccessful: totalSuccessful,
		TotalFailed:     totalFailed,
		P50:             percentile(values, 0.50),
		P90:             percentile(values, 0.90),
		P99:             percentile(values, 0.99),
		WorstPods:       worstPods,
		FailedPods:      failedPods,
	}, nil
}

func percentile(sorted []int64, p float64) int64 {
	index := int(float64(len(sorted)-1) * p)
	return sorted[index]
}

func (m *MetricsCalculator) GetPodHealth(ctx context.Context, namespace string, labels map[string]string, topN int) (*PodHealthResult, error) {
	var podList corev1.PodList
	opts := []client.ListOption{}
	if namespace != "" {
		opts = append(opts, client.InNamespace(namespace))
	}
	if len(labels) > 0 {
		opts = append(opts, client.MatchingLabels(labels))
	}

	if err := m.Client.List(ctx, &podList, opts...); err != nil {
		return nil, err
	}

	runningPods := 0
	pendingPods := 0
	failedPods := 0
	pendingPodList := []PodDetails{}
	failedPodList := []PodDetails{}

	for _, pod := range podList.Items {
		switch pod.Status.Phase {
		case corev1.PodRunning:
			runningPods++
		case corev1.PodPending:
			pendingPods++
			pendingPodList = append(pendingPodList, PodDetails{
				Namespace: pod.Namespace,
				Name:      pod.Name,
				UID:       string(pod.UID),
				NodeName:  pod.Spec.NodeName,
				Phase:     string(pod.Status.Phase),
				Reason:    pod.Status.Reason,
				Message:   pod.Status.Message,
			})
		case corev1.PodFailed:
			failedPods++
			failedPodList = append(failedPodList, PodDetails{
				Namespace: pod.Namespace,
				Name:      pod.Name,
				UID:       string(pod.UID),
				NodeName:  pod.Spec.NodeName,
				Phase:     string(pod.Status.Phase),
				Reason:    pod.Status.Reason,
				Message:   pod.Status.Message,
			})
		}
	}

	// Limit lists to topN
	if len(pendingPodList) > topN {
		pendingPodList = pendingPodList[:topN]
	}
	if len(failedPodList) > topN {
		failedPodList = failedPodList[:topN]
	}

	desiredReplicas := len(podList.Items)
	successPct := 0.0
	if desiredReplicas > 0 {
		successPct = float64(runningPods) * 100.0 / float64(desiredReplicas)
	}

	labelSelectorStr := ""
	if len(labels) > 0 {
		parts := []string{}
		for k, v := range labels {
			parts = append(parts, k+"="+v)
		}
		labelSelectorStr = strings.Join(parts, ",")
	}

	return &PodHealthResult{
		Namespace:       namespace,
		LabelSelector:   labelSelectorStr,
		DesiredReplicas: desiredReplicas,
		RunningPods:     runningPods,
		PendingPods:     pendingPods,
		FailedPods:      failedPods,
		SuccessPct:      successPct,
		PendingPodList:  pendingPodList,
		FailedPodList:   failedPodList,
	}, nil
}
