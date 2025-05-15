# Kustomize

## Installation

- Use the following commands to install Kustomize or choose your desired installation method using this [guide](https://kubectl.docs.kubernetes.io/installation/kustomize/):

```bash
curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh"  | bash
sudo mv kustomize /usr/local/bin
```

- Verify version

```bash
kubectl version --client
kustomize version
```

## Reference

- [Introduction](https://kubectl.docs.kubernetes.io/guides/introduction/kustomize/)
- [Source code](https://github.com/kubernetes-sigs/kustomize)
- [Kubernetes](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)
