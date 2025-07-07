import argparse
import sys
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
import requests
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def get_headers(pat):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {pat}",
    }


def get_pipeline_definition(org, project, pipeline_id, headers):
    url = (
        f"https://dev.azure.com/{org}/{project}/_apis/build/definitions/{pipeline_id}"
        f"?api-version=7.1-preview.7"
    )
    res = requests.get(url, headers=headers, timeout=10)
    res.raise_for_status()
    return res.json()


def get_scheduled_pipelines(org, project, headers):
    min_time = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    max_time = datetime.now(timezone.utc).isoformat()

    min_time_encoded = quote(min_time)
    max_time_encoded = quote(max_time)
    url = (
        f"https://dev.azure.com/{org}/{project}/_apis/build/builds"
        f"?reasonFilter=schedule"
        f"&maxBuildsPerDefinition=1"
        f"&minTime={min_time_encoded}"
        f"&maxTime={max_time_encoded}"
        f"&api-version=7.1-preview.7"
    )
    res = requests.get(url, headers=headers, timeout=10)
    res.raise_for_status()
    return res.json()["value"]


def should_disable_pipeline(pipeline_def, source_branch=None, excluded_ids=None):
    """Check if pipeline should be disabled based on various criteria

    Args:
        pipeline_def: The pipeline definition to check
        source_branch: The source branch of the pipeline
        excluded_ids: List of pipeline IDs that should be excluded from disabling

    Returns:
        tuple: (should_disable, reason) where:
            - should_disable is a boolean indicating if pipeline should be disabled
            - reason is a string explaining why it should be disabled (or None)
    """
    # Check if pipeline is excluded from disabling
    if excluded_ids and pipeline_def["id"] in excluded_ids:
        logger.warning(
            f"Pipeline '{pipeline_def['path']} {pipeline_def['name']}' (ID: {pipeline_def['id']}) is excluded from disabling"
        )
        return False, "Pipeline is explicitly excluded"

    # Check if pipeline has SKIP_RESOURCE_MANAGEMENT=true
    if (
        "variables" in pipeline_def
        and "SKIP_RESOURCE_MANAGEMENT" in pipeline_def["variables"]
    ):
        skip_resource_mgmt = (
            pipeline_def["variables"]["SKIP_RESOURCE_MANAGEMENT"]
            .get("value", "false")
            .lower()
        )
        if skip_resource_mgmt == "true":
            return True, "SKIP_RESOURCE_MANAGEMENT is set to true"

    # Check if pipeline is not on main branch
    if source_branch and source_branch != "refs/heads/main":
        return True, f"Pipeline is scheduled on non-main branch: {source_branch}"

    return False, None


def disable_pipeline(org, project, pipeline_def, headers, reason=None):
    """Disable a pipeline by updating its queue status.

    Args:
        org: Azure DevOps organization
        project: Azure DevOps project
        pipeline_def: Pipeline definition to disable
        headers: Request headers containing authentication
        reason: Reason for disabling the pipeline
    """
    pipeline_def["queueStatus"] = "disabled"

    definition_id = pipeline_def["id"]
    logger.info(
        f"Disabling pipeline: {pipeline_def['name']} under {pipeline_def['path']}, reason: {reason}"
    )
    url = f"https://dev.azure.com/{org}/{project}/_apis/build/definitions/{definition_id}?api-version=7.1-preview.7"
    res = requests.put(url, json=pipeline_def, headers=headers, timeout=10)
    res.raise_for_status()


def main():
    parser = argparse.ArgumentParser(
        description="Validate and disable ADO pipelines not scheduled on 'main' branch."
    )
    parser.add_argument("--org", required=True, help="Azure DevOps organization name")
    parser.add_argument("--project", required=True, help="Azure DevOps project name")
    parser.add_argument("--pat", required=True, help="Personal Access Token (PAT)")
    parser.add_argument(
        "--exclude-pipelines",
        nargs="+",
        default=[],
        help="List of pipeline IDs to exclude from disabling",
    )

    args = parser.parse_args()
    org, project, pat = args.org, args.project, args.pat
    headers = get_headers(pat)
    excluded_ids = list(map(int, args.exclude_pipelines))
    logger.info(f"Excluded pipeline IDs: {excluded_ids}")

    pipelines_to_disable = []

    try:
        scheduled_pipelines = get_scheduled_pipelines(org, project, headers)
        for p in scheduled_pipelines:
            source_branch = p["sourceBranch"]
            pipeline_def = get_pipeline_definition(
                org, project, p["definition"]["id"], headers
            )

            # Centralized check for disabling pipelines
            should_disable, reason = should_disable_pipeline(
                pipeline_def=pipeline_def,
                source_branch=source_branch,
                excluded_ids=excluded_ids,
            )

            if should_disable and pipeline_def["queueStatus"] != "disabled":
                logger.warning(
                    f"Pipeline '{p['definition']['path']} {p['definition']['name']}' (ID: {pipeline_def['id']}) will be disabled due to: {reason}"
                )
                # Store reason with pipeline definition for later use
                pipeline_def["comment"] = f"Disabled by script: {reason}"
                pipelines_to_disable.append(pipeline_def)
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(1)

    for pipeline_def in pipelines_to_disable:
        try:
            # Pass the reason for disabling to the function
            reason = pipeline_def.get("comment", None)
            disable_pipeline(org, project, pipeline_def, headers, reason=reason)
        except Exception as e:
            logger.error(f"Failed to disable pipeline {pipeline_def['id']}: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
