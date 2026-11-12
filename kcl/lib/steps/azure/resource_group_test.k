import regex

test_delete_resource_group_keeps_existing_behavior = lambda {
    step = DeleteResourceGroup("connection", "group", "subscription")
    assert step.condition == "always()"
    assert step.inputs.inlineScript == "set -exo pipefail\n" + """
az group delete --name "group" --subscription "subscription" --yes
"""
}

test_delete_resource_group_async = lambda {
    step = DeleteResourceGroupAsync("connection", "group", "subscription")
    assert step.condition == "always()"
    assert step.inputs.inlineScript == "set -exo pipefail\n" + """
python3 "$(Build.SourcesDirectory)/kcl/lib/steps/azure/resource_group.py" delete \\
  --resource-group "group" \\
  --subscription "subscription" \\
  --timeout-seconds 2700 \\
  --poll-interval-seconds 30
"""
}

test_delete_resource_group_async_custom_options = lambda {
    step = DeleteResourceGroupAsync(
        "connection",
        "group",
        "subscription",
        condition = "succeeded()",
        timeoutSeconds = 100,
        pollIntervalSeconds = 2)
    assert step.condition == "succeeded()"
    assert regex.match(step.inputs.inlineScript, "timeout-seconds 100")
    assert regex.match(step.inputs.inlineScript, "poll-interval-seconds 2")
}
