test_single_sku_under_max = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 500})
    assert pools == [
        NodePool {name = "workerpool0", sku = "Standard_D8s_v4", count = 500},
    ]
}

test_single_sku_exactly_max = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 800})
    assert pools == [
        NodePool {name = "workerpool0", sku = "Standard_D8s_v4", count = 800},
    ]
}

test_single_sku_over_max = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 1700})
    assert pools == [
        NodePool {name = "workerpool0", sku = "Standard_D8s_v4", count = 800},
        NodePool {name = "workerpool1", sku = "Standard_D8s_v4", count = 800},
        NodePool {name = "workerpool2", sku = "Standard_D8s_v4", count = 100},
    ]
}

test_multiple_skus = lambda {
    # workerpool indices are globally assigned across SKUs
    # 1700 -> 800+800+100, 900 -> 800+100
    pools = PlanNodePools({"Standard_D8s_v4": 1700, "Standard_D4s_v4": 900})
    assert pools == [
        NodePool {name = "workerpool0", sku = "Standard_D8s_v4", count = 800},
        NodePool {name = "workerpool1", sku = "Standard_D8s_v4", count = 800},
        NodePool {name = "workerpool2", sku = "Standard_D8s_v4", count = 100},
        NodePool {name = "workerpool3", sku = "Standard_D4s_v4", count = 800},
        NodePool {name = "workerpool4", sku = "Standard_D4s_v4", count = 100},
    ]
}

test_skips_zero_count_skus = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 100, "Standard_D4s_v4": 0})
    assert pools == [
        NodePool {name = "workerpool0", sku = "Standard_D8s_v4", count = 100},
    ]
}

test_empty_map = lambda {
    pools = PlanNodePools({})
    assert pools == []
}

test_custom_max_nodes_per_pool = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 250}, 100)
    assert pools == [
        NodePool {name = "workerpool0", sku = "Standard_D8s_v4", count = 100},
        NodePool {name = "workerpool1", sku = "Standard_D8s_v4", count = 100},
        NodePool {name = "workerpool2", sku = "Standard_D8s_v4", count = 50},
    ]
}

test_exact_divisible_by_custom_max = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 300}, 100)
    assert pools == [
        NodePool {name = "workerpool0", sku = "Standard_D8s_v4", count = 100},
        NodePool {name = "workerpool1", sku = "Standard_D8s_v4", count = 100},
        NodePool {name = "workerpool2", sku = "Standard_D8s_v4", count = 100},
    ]
}
