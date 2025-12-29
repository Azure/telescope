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

package v1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// DatapathResultSpec defines the desired state of DatapathResult
type DatapathResultSpec struct {
	PodRef     PodReference      `json:"podRef"`
	Timestamps Timestamps        `json:"timestamps"`
	Metrics    Metrics           `json:"metrics"`
	Labels     map[string]string `json:"labels,omitempty"`
}

type PodReference struct {
	Namespace string `json:"namespace"`
	Name      string `json:"name"`
	UID       string `json:"uid"`
}

type Timestamps struct {
	CreatedAt string `json:"createdAt"`
	StartTs   string `json:"startTs,omitempty"`
	DpReadyTs string `json:"dpReadyTs,omitempty"`
}

type Metrics struct {
	LatStartMs   int64 `json:"latStartMs,omitempty"`
	LatDpReadyMs int64 `json:"latDpReadyMs,omitempty"`
}

// DatapathResultStatus defines the observed state of DatapathResult
type DatapathResultStatus struct {
	// INSERT ADDITIONAL STATUS FIELD - define observed state of cluster
	// Important: Run "make" to regenerate code after modifying this file
}

//+kubebuilder:object:root=true
//+kubebuilder:subresource:status

// DatapathResult is the Schema for the datapathresults API
type DatapathResult struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   DatapathResultSpec   `json:"spec,omitempty"`
	Status DatapathResultStatus `json:"status,omitempty"`
}

//+kubebuilder:object:root=true

// DatapathResultList contains a list of DatapathResult
type DatapathResultList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []DatapathResult `json:"items"`
}

func init() {
	SchemeBuilder.Register(&DatapathResult{}, &DatapathResultList{})
}
