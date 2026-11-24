# Registry identity for Azure Resource Consumer benchmarks

Ubuntu, Secure TLS, Windows, Flatcar and Azure Linux Resource Consumer jobs
use `telescope-controlplane-MI` and `cri-kubelet` from the persistent
`telescope` resource group. The Azure provisioning step resolves their IDs at
runtime in the `AKS Airlock` subscription (`CRI_IDENTITY_SUBSCRIPTION` can
specify the subscription ID if the name is ambiguous). Neither identity nor
its registry grants are owned by an individual run. AWS is unchanged.

The kubelet needs `AcrPull` on `akscritelescope`. The control plane needs
`Managed Identity Operator` on the kubelet identity and permission to manage
the infrastructure used by the scenario (including any custom subnet).
The provisioning principal must be able to read and assign the identities.

Before rollout, create fresh AzureRM and CLI clusters on a canary branch.
Compare `az aks show`'s `identity.userAssignedIdentities` and
`identityProfile.kubeletidentity.objectId` with the configured identities.
Verify cold Linux and Windows workload pulls against a private canary ACR
authorized for the same kubelet. Include Secure TLS and OS Guard, and confirm
cluster teardown leaves both identities and their grants intact.
