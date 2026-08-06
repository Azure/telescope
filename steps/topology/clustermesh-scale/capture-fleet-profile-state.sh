#!/usr/bin/env bash

set -euo pipefail

fleet_rg="${FLEET_RG:?FLEET_RG is required}"
fleet_name="${FLEET_NAME:?FLEET_NAME is required}"
fleet_profile="${FLEET_PROFILE:?FLEET_PROFILE is required}"
capture_dir="${FLEET_STATE_CAPTURE_DIR:-$(pwd)/clustermeshprofile-state}"
capture_reason="${FLEET_STATE_CAPTURE_REASON:-snapshot}"
query_timeout_seconds="${FLEET_QUERY_TIMEOUT_SECONDS:-60}"

safe_reason=$(printf '%s' "$capture_reason" | tr -c 'A-Za-z0-9._-' '-')
profile_file="$capture_dir/clustermeshprofile-${safe_reason}.json"
members_file="$capture_dir/clustermeshprofile-members-${safe_reason}.json"
profile_tmp=""
members_tmp=""
profile_error=""
members_error=""

mkdir -p "$capture_dir"
profile_tmp=$(mktemp "$capture_dir/.profile.XXXXXX")
members_tmp=$(mktemp "$capture_dir/.members.XXXXXX")
profile_error=$(mktemp "$capture_dir/.profile-error.XXXXXX")
members_error=$(mktemp "$capture_dir/.members-error.XXXXXX")

cleanup() {
  rm -f "$profile_tmp" "$members_tmp" "$profile_error" "$members_error"
}
trap cleanup EXIT

captured=0
if timeout "${query_timeout_seconds}s" az fleet clustermeshprofile show \
    --resource-group "$fleet_rg" \
    --fleet-name "$fleet_name" \
    --name "$fleet_profile" \
    --output json \
    --only-show-errors > "$profile_tmp" 2> "$profile_error" &&
  jq -e . "$profile_tmp" >/dev/null; then
  mv -f "$profile_tmp" "$profile_file"
  captured=1
  echo "[fleet-state] profile snapshot: $profile_file"
  jq -c '{
    id: (.id // null),
    name: (.name // null),
    provisioningState: (
      .properties.provisioningState // .provisioningState // "<unset>"
    )
  }' "$profile_file" |
    sed 's/^/[fleet-state] profile=/'
  echo "##vso[task.uploadfile]$profile_file"
else
  echo "##vso[task.logissue type=warning;] [fleet-state] unable to capture profile: $(tr '\n' ' ' < "$profile_error")"
fi

if timeout "${query_timeout_seconds}s" az fleet clustermeshprofile list-members \
    --resource-group "$fleet_rg" \
    --fleet-name "$fleet_name" \
    --name "$fleet_profile" \
    --output json \
    --only-show-errors > "$members_tmp" 2> "$members_error" &&
  jq -e 'type == "array"' "$members_tmp" >/dev/null; then
  mv -f "$members_tmp" "$members_file"
  captured=1
  echo "[fleet-state] member snapshot: $members_file"
  jq -r '
    map(.meshProperties.status.state // "<unset>")
    | sort
    | group_by(.)
    | .[]
    | "[fleet-state] member-state state=\(.[0]) count=\(length)"
  ' "$members_file"
  jq -c '
    .[]
    | {
        name: (.name // .memberName // .id // "<unknown>"),
        meshProperties: (.meshProperties // null)
      }
  ' "$members_file" |
    sed 's/^/[fleet-state] raw-member=/'
  echo "##vso[task.uploadfile]$members_file"
else
  echo "##vso[task.logissue type=warning;] [fleet-state] unable to capture profile members: $(tr '\n' ' ' < "$members_error")"
fi

if [ "$captured" -eq 0 ]; then
  exit 1
fi
