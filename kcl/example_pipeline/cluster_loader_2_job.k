import k8s.api.batch.v1 as batch
import k8s.api.core.v1 as corev1

image = option("image")
testConfig = option("testConfig")
namespace = option("namespace", default="default")
nodePool = option("nodePool")
taint = option("taint", default="")

output = batch.Job {
    metadata.name = "cl2"
    metadata.namespace = namespace
    spec.template.spec = corev1.PodSpec {
        restartPolicy = "Never"
        nodeSelector = {
            "agentpool" = nodePool
        }
        tolerations = [corev1.Toleration {
            key = taint
            operator = "Exists"
            effect = "NoSchedule"
        }] if taint else []
        containers = [corev1.Container {
            name = "cl2"
            image = image
            args = [
                "--provider=aks"
                "--kubeconfig=/root/.kube/config"
                "--testconfig=${testConfig}"
                "--v=2"
            ]
            resources = corev1.ResourceRequirements {
                requests = {
                    cpu = "1"
                    memory = "2Gi"
                }
            }
        }]
    }
}
