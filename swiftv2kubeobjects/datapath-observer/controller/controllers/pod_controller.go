/*
Copyright 2025.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controllers

import (
	"context"
	"fmt"
	"strings"
	"time"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller"
	"sigs.k8s.io/controller-runtime/pkg/event"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"

	perfv1 "github.com/Azure/datapath-observer/controller/api/v1"
)

// PodReconciler reconciles a Pod object
type PodReconciler struct {
	client.Client
	Scheme                  *runtime.Scheme
	Namespace               string
	LabelSelector           string
	MaxConcurrentReconciles int
}

//+kubebuilder:rbac:groups=core,resources=pods,verbs=get;list;watch
//+kubebuilder:rbac:groups=perf.github.com,resources=datapathresults,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=perf.github.com,resources=datapathresults/status,verbs=get;update;patch

func (r *PodReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	_ = log.FromContext(ctx)

	// Fetch the Pod
	var pod corev1.Pod
	if err := r.Get(ctx, req.NamespacedName, &pod); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Check for annotations
	startTsStr, _ := pod.Annotations["perf.github.com/azure-start-ts"]
	dpReadyTsStr, _ := pod.Annotations["perf.github.com/azure-dp-ready-ts"]

	dpResultName := fmt.Sprintf("dpresult-%s", pod.UID)

	dpResult := &perfv1.DatapathResult{
		ObjectMeta: metav1.ObjectMeta{
			Name:      dpResultName,
			Namespace: pod.Namespace,
		},
	}

	// CreateOrUpdate handles both create and update in one atomic operation
	// This avoids race conditions from concurrent reconciliations
	_, err := ctrl.CreateOrUpdate(ctx, r.Client, dpResult, func() error {
		// Set immutable fields only if they're empty (on create)
		if dpResult.Spec.PodRef.UID == "" {
			dpResult.Spec.PodRef = perfv1.PodReference{
				Namespace: pod.Namespace,
				Name:      pod.Name,
				UID:       string(pod.UID),
			}
			dpResult.Spec.Timestamps.CreatedAt = pod.CreationTimestamp.Format(time.RFC3339Nano)
			dpResult.Spec.Labels = pod.Labels
		}

		// Always update mutable fields
		dpResult.Spec.PodRef.NodeName = pod.Spec.NodeName

		// Update timestamps and recalculate metrics
		updateMetrics(dpResult, pod.CreationTimestamp.Time, startTsStr, dpReadyTsStr)

		return nil
	})

	if err != nil {
		// In rare cases, CreateOrUpdate can still hit race conditions with "already exists"
		// when multiple reconcilers create simultaneously. Requeue to update on next pass.
		if errors.IsAlreadyExists(err) {
			return ctrl.Result{Requeue: true}, nil
		}
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

func updateMetrics(dpResult *perfv1.DatapathResult, createdAt time.Time, startTsStr, dpReadyTsStr string) {
	logger := log.Log.WithName("updateMetrics").WithValues("dpResult", dpResult.Name, "namespace", dpResult.Namespace)
	
	// Only update startTs if not already set (capture first occurrence from initContainer)
	if startTsStr != "" && dpResult.Spec.Timestamps.StartTs == "" {
		dpResult.Spec.Timestamps.StartTs = startTsStr
		startTs, err := time.Parse(time.RFC3339Nano, strings.TrimSpace(startTsStr))
		if err != nil {
			logger.Error(err, "Failed to parse start timestamp", "startTsStr", startTsStr, "createdAt", createdAt.Format(time.RFC3339Nano))
		} else {
			dpResult.Spec.Metrics.LatStartMs = startTs.Sub(createdAt).Milliseconds()
			logger.V(1).Info("Calculated LatStartMs", "createdAt", createdAt.Format(time.RFC3339Nano), "startTs", startTs.Format(time.RFC3339Nano), "latMs", dpResult.Spec.Metrics.LatStartMs)
		}
	}
	
	// Only update dpReadyTs if not already set (capture first occurrence from initContainer)
	if dpReadyTsStr != "" && dpResult.Spec.Timestamps.DpReadyTs == "" {
		dpResult.Spec.Timestamps.DpReadyTs = dpReadyTsStr
		dpReadyTs, err := time.Parse(time.RFC3339Nano, strings.TrimSpace(dpReadyTsStr))
		if err != nil {
			logger.Error(err, "Failed to parse dpReady timestamp", "dpReadyTsStr", dpReadyTsStr, "createdAt", createdAt.Format(time.RFC3339Nano))
		} else {
			dpResult.Spec.Metrics.LatDpReadyMs = dpReadyTs.Sub(createdAt).Milliseconds()
			logger.V(1).Info("Calculated LatDpReadyMs", "createdAt", createdAt.Format(time.RFC3339Nano), "dpReadyTs", dpReadyTs.Format(time.RFC3339Nano), "latMs", dpResult.Spec.Metrics.LatDpReadyMs)
		}
	}
}

func (r *PodReconciler) SetupWithManager(mgr ctrl.Manager) error {
	builder := ctrl.NewControllerManagedBy(mgr).
		For(&corev1.Pod{}).
		WithOptions(controller.Options{
			MaxConcurrentReconciles: r.MaxConcurrentReconciles,
		})

	// Apply namespace filter if specified
	if r.Namespace != "" {
		builder = builder.WithEventFilter(namespaceFilter(r.Namespace))
	}

	// Apply label selector filter if specified
	if r.LabelSelector != "" {
		builder = builder.WithEventFilter(labelSelectorFilter(r.LabelSelector))
	}

	return builder.Complete(r)
}

func namespaceFilter(namespace string) predicate.Predicate {
	return predicate.Funcs{
		CreateFunc: func(e event.CreateEvent) bool {
			return e.Object.GetNamespace() == namespace
		},
		UpdateFunc: func(e event.UpdateEvent) bool {
			if e.ObjectNew.GetNamespace() != namespace {
				return false
			}
			return hasRelevantChange(e.ObjectOld, e.ObjectNew)
		},
		DeleteFunc: func(e event.DeleteEvent) bool {
			return false
		},
		GenericFunc: func(e event.GenericEvent) bool {
			return e.Object.GetNamespace() == namespace
		},
	}
}

func labelSelectorFilter(selector string) predicate.Predicate {
	// Parse selector string (e.g., "app=perf-sut")
	pairs := strings.Split(selector, ",")
	selectorMap := make(map[string]string)
	for _, pair := range pairs {
		parts := strings.SplitN(strings.TrimSpace(pair), "=", 2)
		if len(parts) == 2 {
			selectorMap[parts[0]] = parts[1]
		}
	}

	return predicate.Funcs{
		CreateFunc: func(e event.CreateEvent) bool {
			return matchLabels(e.Object.GetLabels(), selectorMap)
		},
		UpdateFunc: func(e event.UpdateEvent) bool {
			if !matchLabels(e.ObjectNew.GetLabels(), selectorMap) {
				return false
			}
			return hasRelevantChange(e.ObjectOld, e.ObjectNew)
		},
		DeleteFunc: func(e event.DeleteEvent) bool {
			return false
		},
		GenericFunc: func(e event.GenericEvent) bool {
			return matchLabels(e.Object.GetLabels(), selectorMap)
		},
	}
}

func matchLabels(objLabels, selector map[string]string) bool {
	for key, val := range selector {
		if objLabels[key] != val {
			return false
		}
	}
	return true
}

func hasRelevantChange(oldObj, newObj client.Object) bool {
	oldAnnotations := oldObj.GetAnnotations()
	newAnnotations := newObj.GetAnnotations()

	// Check if start-ts annotation was added or changed
	oldStartTs := oldAnnotations["perf.github.com/azure-start-ts"]
	newStartTs := newAnnotations["perf.github.com/azure-start-ts"]
	if oldStartTs != newStartTs {
		return true
	}

	// Check if dp-ready-ts annotation was added or changed
	oldDpReadyTs := oldAnnotations["perf.github.com/azure-dp-ready-ts"]
	newDpReadyTs := newAnnotations["perf.github.com/azure-dp-ready-ts"]
	if oldDpReadyTs != newDpReadyTs {
		return true
	}

	// Check if NodeName was added or changed (pod got scheduled)
	oldPod, oldOk := oldObj.(*corev1.Pod)
	newPod, newOk := newObj.(*corev1.Pod)
	if oldOk && newOk {
		if oldPod.Spec.NodeName != newPod.Spec.NodeName {
			return true
		}
	}

	return false
}
