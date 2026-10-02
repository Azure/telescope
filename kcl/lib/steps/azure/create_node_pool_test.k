# Whitespace-normalized script: one line, single spaces between tokens.
normalizedScript = lambda pool: NodePool -> str {
    " ".join([line.strip() for line in CreateNodePool("sc", "cluster", "rg", "sub", pool).inputs.inlineScript.split("\n")])
}

test_autoscaler_and_os_disk_flags = lambda {
    script = normalizedScript(NodePool {
        name = "userpool"
        sku = "Standard_D8s_v3"
        count = 1
        minCount = 1
        maxCount = 10
        osDiskType = "Ephemeral"
    })
    assert "--node-vm-size \"Standard_D8s_v3\" \\ --mode User \\ --enable-cluster-autoscaler \\ --min-count 1 \\ --max-count 10 \\ --node-osdisk-type Ephemeral 2>&1)" in script, script
}

test_no_autoscaler_or_os_disk_flags_by_default = lambda {
    script = normalizedScript(NodePool {
        name = "workerpool0"
        sku = "Standard_D8s_v4"
        count = 4
    })
    assert "--node-vm-size \"Standard_D8s_v4\" \\ --mode User \\ 2>&1)" in script, script
}
