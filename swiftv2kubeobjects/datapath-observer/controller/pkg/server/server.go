package server

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"

	"github.com/Azure/datapath-observer/controller/pkg/metrics"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type Server struct {
	Calculator *metrics.MetricsCalculator
}

func NewServer(c client.Client) *Server {
	return &Server{
		Calculator: &metrics.MetricsCalculator{Client: c},
	}
}

func (s *Server) Start(addr string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/time-to-start", s.handleTimeToStart)
	mux.HandleFunc("/api/v1/time-to-datapath-ready", s.handleTimeToDatapathReady)
	return http.ListenAndServe(addr, mux)
}

func (s *Server) handleTimeToStart(w http.ResponseWriter, r *http.Request) {
	s.handleMetric(w, r, s.Calculator.GetTimeToStart)
}

func (s *Server) handleTimeToDatapathReady(w http.ResponseWriter, r *http.Request) {
	s.handleMetric(w, r, s.Calculator.GetTimeToDatapathReady)
}

func (s *Server) handleMetric(w http.ResponseWriter, r *http.Request, calculatorFunc func(context.Context, string, map[string]string, int) (*metrics.AggregatedResult, error)) {
	query := r.URL.Query()
	namespace := query.Get("namespace")
	topNStr := query.Get("topN")
	topN := 10
	if topNStr != "" {
		if val, err := strconv.Atoi(topNStr); err == nil {
			topN = val
		}
	}

	labelSelectorStr := query.Get("labelSelector")
	labels := make(map[string]string)
	if labelSelectorStr != "" {
		parts := strings.Split(labelSelectorStr, ",")
		for _, part := range parts {
			kv := strings.Split(part, "=")
			if len(kv) == 2 {
				labels[kv[0]] = kv[1]
			}
		}
	}

	result, err := calculatorFunc(r.Context(), namespace, labels, topN)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}
