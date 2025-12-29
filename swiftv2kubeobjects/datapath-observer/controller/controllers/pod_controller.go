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
	"time"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	perfv1 "github.com/Azure/datapath-observer/controller/api/v1"
)

// PodReconciler reconciles a Pod object
type PodReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

//+kubebuilder:rbac:groups=core,resources=pods,verbs=get;list;watch
//+kubebuilder:rbac:groups=perf.github.com/Azure,resources=datapathresults,verbs=get;list;watch;create;update;patch;delete
//+kubebuilder:rbac:groups=perf.github.com/Azure,resources=datapathresults/status,verbs=get;update;patch

func (r *PodReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	_ = log.FromContext(ctx)

	// Fetch the Pod
	var pod corev1.Pod
	if err := r.Get(ctx, req.NamespacedName, &pod); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Check for annotations
	startTsStr, hasStart := pod.Annotations["perf.github.com/Azure/start-ts"]
	dpReadyTsStr, hasDpReady := pod.Annotations["perf.github.com/Azure/dp-ready-ts"]

	dpResultName := fmt.Sprintf("dpresult-%s", pod.UID)

	var dpResult perfv1.DatapathResult
	err := r.Get(ctx, client.ObjectKey{Name: dpResultName, Namespace: pod.Namespace}, &dpResult)

	if errors.IsNotFound(err) {
		// Create
		dpResult = perfv1.DatapathResult{
			ObjectMeta: metav1.ObjectMeta{
				Name:      dpResultName,
				Namespace: pod.Namespace,
			},
			Spec: perfv1.DatapathResultSpec{
				PodRef: perfv1.PodReference{
					Namespace: pod.Namespace,
					Name:      pod.Name,
					UID:       string(pod.UID),
				},
				Timestamps: perfv1.Timestamps{
					CreatedAt: pod.CreationTimestamp.Format(time.RFC3339),
				},
				Labels: pod.Labels,
			},
		}
		// Calculate metrics if annotations exist
		updateMetrics(&dpResult, pod.CreationTimestamp.Time, startTsStr, dpReadyTsStr)

		if err := r.Create(ctx, &dpResult); err != nil {
			return ctrl.Result{}, err
		}
	} else if err == nil {
		// Update
		updated := false
		if hasStart && dpResult.Spec.Timestamps.StartTs != startTsStr {
			dpResult.Spec.Timestamps.StartTs = startTsStr
			updated = true
		}
		if hasDpReady && dpResult.Spec.Timestamps.DpReadyTs != dpReadyTsStr {
			dpResult.Spec.Timestamps.DpReadyTs = dpReadyTsStr
			updated = true
		}

		if updated {
			updateMetrics(&dpResult, pod.CreationTimestamp.Time, startTsStr, dpReadyTsStr)
			if err := r.Update(ctx, &dpResult); err != nil {
				return ctrl.Result{}, err
			}
		}
	} else {
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

func updateMetrics(dpResult *perfv1.DatapathResult, createdAt time.Time, startTsStr, dpReadyTsStr string) {
	if startTsStr != "" {
		dpResult.Spec.Timestamps.StartTs = startTsStr
		startTs, err := time.Parse(time.RFC3339, startTsStr)
		if err == nil {
			dpResult.Spec.Metrics.LatStartMs = startTs.Sub(createdAt).Milliseconds()
		}
	}
	if dpReadyTsStr != "" {
		dpResult.Spec.Timestamps.DpReadyTs = dpReadyTsStr
		dpReadyTs, err := time.Parse(time.RFC3339, dpReadyTsStr)
		if err == nil {
			dpResult.Spec.Metrics.LatDpReadyMs = dpReadyTs.Sub(createdAt).Milliseconds()
		}
	}
}

func (r *PodReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&corev1.Pod{}).
		Complete(r)
}
