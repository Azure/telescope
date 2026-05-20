test_single_sku_under_max = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 500})
    assert len(pools) == 1
    assert pools[0].name == "workerpool0"
    assert pools[0].sku == "Standard_D8s_v4"
    assert pools[0].count == 500
}

test_single_sku_exactly_max = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 800})
    assert len(pools) == 1
    assert pools[0].count == 800
}

test_single_sku_over_max = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 1700})
    assert len(pools) == 3
    assert [p.count for p in pools] == [800, 800, 100]
    assert [p.name for p in pools] == ["workerpool0", "workerpool1", "workerpool2"]
    assert [p.sku for p in pools] == ["Standard_D8s_v4", "Standard_D8s_v4", "Standard_D8s_v4"]
}

test_multiple_skus = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 1700, "Standard_D4s_v4": 800})
    assert len(pools) == 4
    # workerpool indices are globally assigned across SKUs
    assert [p.name for p in pools] == ["workerpool0", "workerpool1", "workerpool2", "workerpool3"]
    # 1700 -> 800+800+100, 800 -> 800
    assert sum([p.count for p in pools], 0) == 2500
}

test_skips_zero_count_skus = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 100, "Standard_D4s_v4": 0})
    assert len(pools) == 1
    assert pools[0].sku == "Standard_D8s_v4"
    assert pools[0].count == 100
}

test_empty_map = lambda {
    pools = PlanNodePools({})
    assert len(pools) == 0
}

test_custom_max_nodes_per_pool = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 250}, 100)
    assert len(pools) == 3
    assert [p.count for p in pools] == [100, 100, 50]
}

test_exact_divisible_by_custom_max = lambda {
    pools = PlanNodePools({"Standard_D8s_v4": 300}, 100)
    assert len(pools) == 3
    assert [p.count for p in pools] == [100, 100, 100]
}
