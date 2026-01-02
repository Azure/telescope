package metrics

import (
	"context"
	"sort"

	perfv1 "github.com/Azure/datapath-observer/controller/api/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type AggregatedResult struct {
	Metric          string     `json:"metric"`
	Unit            string     `json:"unit"`
	Count           int        `json:"count"`
	TotalSuccessful int        `json:"totalSuccessful"`
	TotalFailed     int        `json:"totalFailed"`
	P50             int64      `json:"p50"`
	P90             int64      `json:"p90"`
	P99             int64      `json:"p99"`
	WorstPods       []WorstPod `json:"worstPods"`
	FailedPods      []FailedPod `json:"failedPods"`
}

type WorstPod struct {
	Namespace string `json:"namespace"`
	Name      string `json:"name"`
	UID       string `json:"uid"`
	Value     int64  `json:"value"`
}

type FailedPod struct {
	Namespace string `json:"namespace"`
	Name      string `json:"name"`
	UID       string `json:"uid"`
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
		})
}

func (m *MetricsCalculator) GetTimeToDatapathReady(ctx context.Context, namespace string, labels map[string]string, topN int) (*AggregatedResult, error) {
	return m.calculate(ctx, namespace, labels, topN, "time-to-datapath-ready", 
		func(d perfv1.DatapathResult) int64 {
			return d.Spec.Metrics.LatDpReadyMs
		},
		func(d perfv1.DatapathResult) bool {
			return d.Spec.Timestamps.DpReadyTs != ""
		})
}

func (m *MetricsCalculator) calculate(ctx context.Context, namespace string, labels map[string]string, topN int, metricName string, valueExtractor func(perfv1.DatapathResult) int64, successChecker func(perfv1.DatapathResult) bool) (*AggregatedResult, error) {
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
		// Track success/failure based on timestamp presence
		if successChecker(item) {
			totalSuccessful++
		} else {
			totalFailed++
			failedPods = append(failedPods, FailedPod{
				Namespace: item.Spec.PodRef.Namespace,
				Name:      item.Spec.PodRef.Name,
				UID:       item.Spec.PodRef.UID,
			})
		}

		// Only include in percentile calculations if latency value is non-zero
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
