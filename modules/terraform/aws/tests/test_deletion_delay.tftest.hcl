variables {
  scenario_type  = "perf-eval"
  scenario_name  = "my_scenario"
  deletion_delay = "72h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "us-east-1",
    "creation_time" : timestamp()
  }
}

run "valid_delation_delay_ok" {
  command = plan
}

run "valid_delation_delay_fail" {
  command = plan

  variables {
    deletion_delay = "80h"
  }

  # expected the validation of deletion_delay to throw an error
  expect_failures = [var.deletion_delay]
}
