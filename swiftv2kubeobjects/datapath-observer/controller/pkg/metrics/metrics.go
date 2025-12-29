package metrics

import (
	"context"
	"sort"

	perfv1 "github.com/Azure/telescope/controller/api/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type AggregatedResult struct {
	Metric    string     `json:"metric"`
	Unit      string     `json:"unit"`
	Count     int        `json:"count"`
	P50       int64      `json:"p50"`
	P90       int64      `json:"p90"`
	P99       int64      `json:"p99"`
	WorstPods []WorstPod `json:"worstPods"`
}

type WorstPod struct {
	Namespace string `json:"namespace"`
	Name      string `json:"name"`
	UID       string `json:"uid"`
	Value     int64  `json:"value"`
}

type MetricsCalculator struct {
	Client client.Client
}

func (m *MetricsCalculator) GetTimeToStart(ctx context.Context, namespace string, labels map[string]string, topN int) (*AggregatedResult, error) {
	return m.calculate(ctx, namespace, labels, topN, "time-to-start", func(d perfv1.DatapathResult) int64 {
		return d.Spec.Metrics.LatStartMs
	})
}

func (m *MetricsCalculator) GetTimeToDatapathReady(ctx context.Context, namespace string, labels map[string]string, topN int) (*AggregatedResult, error) {
	return m.calculate(ctx, namespace, labels, topN, "time-to-datapath-ready", func(d perfv1.DatapathResult) int64 {
		return d.Spec.Metrics.LatDpReadyMs
	})
}

func (m *MetricsCalculator) calculate(ctx context.Context, namespace string, labels map[string]string, topN int, metricName string, valueExtractor func(perfv1.DatapathResult) int64) (*AggregatedResult, error) {
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

	for _, item := range list.Items {
		val := valueExtractor(item)
		if val > 0 {
			values = append(values, val)
			worstPods = append(worstPods, WorstPod{
				Namespace: item.Spec.PodRef.Namespace,
				Name:      item.Spec.PodRef.Name,
				UID:       item.Spec.PodRef.UID,
				Value:     val,
			})
		}
	}

	count := len(values)
	if count == 0 {
		return &AggregatedResult{
			Metric: metricName,
			Unit:   "ms",
			Count:  0,
		}, nil
	}

	sort.Slice(values, func(i, j int) bool { return values[i] < values[j] })

	// Sort worstPods descending
	sort.Slice(worstPods, func(i, j int) bool { return worstPods[i].Value > worstPods[j].Value })
	if len(worstPods) > topN {
		worstPods = worstPods[:topN]
	}

	return &AggregatedResult{
		Metric:    metricName,
		Unit:      "ms",
		Count:     count,
		P50:       percentile(values, 0.50),
		P90:       percentile(values, 0.90),
		P99:       percentile(values, 0.99),
		WorstPods: worstPods,
	}, nil
}

func percentile(sorted []int64, p float64) int64 {
	index := int(float64(len(sorted)-1) * p)
	return sorted[index]
}
