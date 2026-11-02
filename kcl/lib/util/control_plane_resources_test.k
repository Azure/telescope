import base64
import json

test_memory_limit_override = lambda {
    overrides = [
        ControlPlaneResourceOverride {
            containerName = "kube-apiserver"
            cpuLimit = "15"
            cpuRequest = "500m"
            memoryLimit = "55Gi"
            memoryRequest = "1500M"
            gomaxprocs = 15
        }
    ]
    encoded = EncodeControlPlaneResourceOverrides(overrides)
    assert json.decode(base64.decode(encoded)) == [
        {
            containerName = "kube-apiserver"
            cpuLimit = "15"
            cpuRequest = "500m"
            memoryLimit = "55Gi"
            memoryRequest = "1500M"
            gomaxprocs = 15
        }
    ]
    assert "\n" not in encoded
    assert "\r" not in encoded
    assert overrides[0].memoryLimit == "55Gi"
    assert overrides[0].cpuLimit == "15"
}

test_full_resource_override = lambda {
    overrides = [
        ControlPlaneResourceOverride {
            containerName = "kube-apiserver"
            cpuLimit = "30"
            cpuRequest = "27"
            memoryLimit = "64Gi"
            memoryRequest = "64Gi"
            gomaxprocs = 30
        }
    ]
    assert json.decode(base64.decode(EncodeControlPlaneResourceOverrides(overrides))) == [
        {
            containerName = "kube-apiserver"
            cpuLimit = "30"
            cpuRequest = "27"
            memoryLimit = "64Gi"
            memoryRequest = "64Gi"
            gomaxprocs = 30
        }
    ]
}

test_multiple_resource_overrides = lambda {
    overrides = [
        ControlPlaneResourceOverride {
            containerName = "kube-apiserver"
            cpuLimit = "15"
            cpuRequest = "500m"
            memoryLimit = "55Gi"
            memoryRequest = "1500M"
            gomaxprocs = 15
        }
        ControlPlaneResourceOverride {
            containerName = "proxy"
            cpuLimit = "1"
            cpuRequest = "500m"
            memoryLimit = "1Gi"
            memoryRequest = "500M"
            gomaxprocs = 1
        }
    ]
    before = json.encode(overrides)
    assert json.decode(base64.decode(EncodeControlPlaneResourceOverrides(overrides))) == [
        {
            containerName = "kube-apiserver"
            cpuLimit = "15"
            cpuRequest = "500m"
            memoryLimit = "55Gi"
            memoryRequest = "1500M"
            gomaxprocs = 15
        }
        {
            containerName = "proxy"
            cpuLimit = "1"
            cpuRequest = "500m"
            memoryLimit = "1Gi"
            memoryRequest = "500M"
            gomaxprocs = 1
        }
    ]
    assert json.encode(overrides) == before
}

test_header_values_without_base64_padding = lambda {
    limits = ["1Gi", "10Gi", "100Gi"]
    overrides = [
        ControlPlaneResourceOverride {
            containerName = "kube-apiserver"
            cpuLimit = "15"
            cpuRequest = "500m"
            memoryLimit = limit
            memoryRequest = "1500M"
            gomaxprocs = 15
        }
        for limit in limits
    ]
    encoded = [
        EncodeControlPlaneResourceOverrides([override])
        for override in overrides
    ]
    assert [value.endswith("=") for value in encoded] == [False, False, False]
    assert [json.decode(base64.decode(value)) for value in encoded] == [
        [{
            containerName = "kube-apiserver"
            cpuLimit = "15"
            cpuRequest = "500m"
            memoryLimit = limit
            memoryRequest = "1500M"
            gomaxprocs = 15
        }]
        for limit in limits
    ]
}
