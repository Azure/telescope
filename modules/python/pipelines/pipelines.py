import argparse
import base64
import sys
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
import requests
def get_headers(pat):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Basic {base64.b64encode(f':{pat}'.encode()).decode()}"
    }

def get_pipeline_definition(org, project, pipeline_id, headers):
    url = f"https://dev.azure.com/{org}/{project}/_apis/build/definitions/{pipeline_id}?api-version=7.1-preview.7"
    res = requests.get(url, headers=headers, timeout=10)
    res.raise_for_status()
    return res.json()

def get_scheduled_pipelines(org, project, headers, min_time=None):
    if not min_time:
        # Default to 2 Hours ago if not provided
        min_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    min_time_encoded = quote(min_time)
    url = (
        f"https://dev.azure.com/{org}/{project}/_apis/build/builds"
        f"?reasonFilter=schedule"
        f"&maxBuildsPerDefinition=1"
        f"&minTime={min_time_encoded}"
        f"&api-version=7.1-preview.7"
    )
    res = requests.get(url, headers=headers, timeout=10)
    res.raise_for_status()
    return res.json()["value"]

def disable_pipeline(org, project, pipeline_def, headers):
    pipeline_def["queueStatus"] = "disabled"
    definition_id = pipeline_def["id"]
    if definition_id == 72:
        url = f"https://dev.azure.com/{org}/{project}/_apis/build/definitions/{definition_id}?api-version=7.1-preview.7"
        res = requests.put(url, json=pipeline_def, headers=headers, timeout=10)
        res.raise_for_status()
        print(f"✅ Disabled pipeline: {pipeline_def['name']} under {pipeline_def['path']}")

def main():
    parser = argparse.ArgumentParser(description="Validate and disable ADO pipelines not scheduled on 'main' branch.")
    parser.add_argument("--org", required=True, help="Azure DevOps organization name")
    parser.add_argument("--project", required=True, help="Azure DevOps project name")
    parser.add_argument("--pat", required=True, help="Personal Access Token (PAT)")

    args = parser.parse_args()
    org, project, pat = args.org, args.project, args.pat
    headers = get_headers(pat)

    pipelines_to_disable = []

    try:
        scheduled_pipelines = get_scheduled_pipelines(org, project, headers)
        print(f"Found {len(scheduled_pipelines)} pipelines in '{project}' project.")
        for p in scheduled_pipelines:
            source_branch = p["sourceBranch"]
            if source_branch != "refs/heads/main":
                print(f"❌ Pipeline '{p['definition']['path']} {p['definition']['name']}' is scheduled on {source_branch} branch.")
                pipelines_to_disable.append(p['definition']['id'])
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)
    if not pipelines_to_disable:
        print("✅ All pipelines are scheduled on 'main' branch.")
        sys.exit(0)

    for pipeline_id in pipelines_to_disable:
        try:
            pipeline_def = get_pipeline_definition(org, project, pipeline_id, headers)
            disable_pipeline(org, project, pipeline_def, headers)
        except Exception as e:
            print(f"❌ Failed to disable pipeline {pipeline_id}: {e}")
            sys.exit(1)
if __name__ == "__main__":
    main()
