import k8s.api.core.v1 as core_v1
import k8s.apimachinery.pkg.apis.meta.v1 as meta_v1

podName = option("podName")
runtimeClass = option("runtimeClass")
image = option("image")

pod: core_v1.Pod = {
    metadata = meta_v1.ObjectMeta {
        name = podName
    }
    spec = core_v1.PodSpec {
        runtimeClassName = runtimeClass
        containers = [{
            name = "pause"
            image = image
        }]
    }
}
