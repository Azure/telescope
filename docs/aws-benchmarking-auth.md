# AWS Benchmarking Authentication

This document describes how Telescope pipelines authenticate to AWS for benchmark runs, covering the current OIDC-based approach and the infrastructure setup required.

## Overview

Telescope uses **OIDC (OpenID Connect) federation** to authenticate Azure DevOps (ADO) pipelines to AWS. Instead of storing long-lived static IAM access keys, the pipeline obtains short-lived temporary credentials at runtime through the AWS Toolkit for Azure DevOps extension.

### Authentication Flow

```
ADO Pipeline
  └─ AWSShellScript@1 task (AWS Toolkit extension)
       ├─ ADO issues an OIDC token via the service connection
       ├─ AWS Toolkit exchanges the token with AWS STS (AssumeRoleWithWebIdentity)
       └─ Injects AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN
            └─ Pipeline exports these as pipeline variables
                 └─ Shared "AWS Login" step configures the AWS CLI
```

### Key Files

| File | Purpose |
|------|---------|
| `steps/cloud/aws/login.yml` | Central AWS auth template used by all AWS pipelines |
| `jobs/competitive-test.yml` | Job template that passes `credential_type` to login |
| `steps/setup-tests.yml` | Passes `credential_type` from job to cloud login |

## Credential Types

The `credential_type` parameter controls how AWS credentials are obtained. It flows from the pipeline → `jobs/competitive-test.yml` → `steps/setup-tests.yml` → `steps/cloud/aws/login.yml`.

### `service_connection` (required for OIDC)

Uses the **AWS Toolkit for Azure DevOps** extension (`AWSShellScript@1` task) with an ADO service connection. This is required for OIDC authentication.

- The service connection is referenced via the `$(AWS_SERVICE_CONNECTION)` pipeline variable
- The extension automatically handles the OIDC token exchange and returns temporary credentials (access key, secret key, session token)

```yaml
# Pipeline usage
credential_type: service_connection
```

> **Note:** The `variable_group` credential type stores static IAM access keys in an ADO variable group, so it does not support OIDC.

## Pipeline Configuration

The ADO service connection `AWS-for-Telescope-OIDC` has been configured with a role in the AWS benchmarking account. To use OIDC authentication, pipelines need to set the following variables:

### `AWS_SERVICE_CONNECTION`

Set this pipeline variable to `AWS-for-Telescope-OIDC`:

```yaml
variables:
  AWS_SERVICE_CONNECTION: AWS-for-Telescope-OIDC
```

### `aws.rolecredential.maxduration`

Controls the credential lifetime in seconds. The AWS IAM role is configured with a maximum session duration of `43200` (12 hours). Pipelines must set `aws.rolecredential.maxduration` to a value less than or equal to `43200` that covers the full duration of the benchmark run:

```yaml
variables:
  aws.rolecredential.maxduration: 43200
```

