import lib.scenario

# cl2.k renders the ClusterLoader2 driver manifest for the Kata benchmark.
#
# Enabling AKS Kata Confidential Containers for the measured workload is a
# single field: `runtimeClassName`. The archetype's manifest builder templates
# it into the override ConfigMap as CL2_RUNTIME_CLASS_NAME, which the in-cluster
# CL2 image stamps onto every workload pod it generates. Everything else inherits
# the shared defaults, so this file stays a couple of lines.
#
# Generate with:
#   kcl run kcl/kata_benchmark/cl2.k -S manifests -o kcl/kata_benchmark/cl2.yaml
manifests = scenario.buildCl2Manifest(scenario.Cl2Manifest {
    override = scenario.Cl2Override {
        runtimeClassName = "kata-mshv-vm-isolation"
    }
})
