import manifests

podName = option("podName")
runtimeClass = option("runtimeClass")
image = option("image")

manifests.yaml_stream([{
    apiVersion = "v1"
    kind = "Pod"
    metadata.name = podName
    spec = {
        runtimeClassName = runtimeClass
        containers = [{
            name = "pause"
            image = image
        }]
    }
}])
