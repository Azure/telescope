# Data connection and Data Ingestion Automation Pipelines

## Summary about pipelines
You can use these pipelines to run the automation for creating kusto tables, event hub instances, subscriptions and data connections to ingest data into kusto from azure storage containers.


# System Database Table and Data Connection Creation:
Pipeline - [System Database Table and Data Connection Creation](https://msazure.visualstudio.com/CloudNativeCompute/_build?definitionId=342761&_a=summary)

Steps and inputs to run this pipeline:
- Go to the pipeline page.
- Select Run Pipeline button to run this pipeline.
![Alt text](data-connection.png)
- Update variables based on your test scenario

Example:

    - SCENARIO_TYPE: perf-eval
    - SCENARIO_NAME: storage-blob
    - SCENARIO_VERSION: v.1.0.15
    - BLOB_STORAGE_URL:https://akstelescope.blob.core.windows.net/perf-eval/storage-blob/v1.0.15/4d15e25a-311d-5c04-78c1-58ba63a0465e-88432383.json

- Click on Run to create the data connections and tables based on the result data from storage account.

- [Successful pipeline run](https://msazure.visualstudio.com/CloudNativeCompute/_build/results?buildId=87481748&view=results)

*NOTES:*
- Make sure SCENARIO_NAME-SCENARIO_VERSION doesn't exceed 40 characters.(Limitations for data connection name)
- Make sure not to use / for SCENARIO_VERSION name.( limitations for consumer group name)

# System Data Ingestion from Blob Storage:

Pipeline -[System Data Ingestion from Blob Storage)](https://msazure.visualstudio.com/CloudNativeCompute/_build?definitionId=345697)

Steps and inputs to run this pipeline:
- Go to the pipeline page.
- Select Run Pipeline button to run this pipeline.
![Alt text](Ingestion.png)
- Update variables based on your test scenario

Example:

    - SCENARIO_TYPE: perf-eval
    - SCENARIO_NAME: vm-iperf
    - SCENARIO_VERSION: v.1.0.10
    - CONTAINER_NAME:
    - CONTAINER_VERSION:

- CONTAINER_NAME & CONTAINER_VERSION are optional empty variables.
- We use these variables to ingest data from another folder prefix within the same storage container.
- Click on Run to create the data connections and tables based on the result data from storage account.

- [Successful pipeline run](https://msazure.visualstudio.com/CloudNativeCompute/_build/results?buildId=87483539&view=logs&j=36a08b4a-8fb0-5483-406c-cef72de14512&t=8680e7ae-c3d4-5dab-593a-979ba4750c3a)