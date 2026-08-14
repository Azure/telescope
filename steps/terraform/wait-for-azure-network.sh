#!/usr/bin/env bash

set -euo pipefail

: "${ARM_SUBSCRIPTION_ID:?ARM_SUBSCRIPTION_ID is required}"
: "${NETWORK_RESOURCE_GROUP:?NETWORK_RESOURCE_GROUP is required}"
: "${NETWORK_VNET_NAME:?NETWORK_VNET_NAME is required}"
: "${NETWORK_SUBNET_REQUIREMENTS_JSON:?NETWORK_SUBNET_REQUIREMENTS_JSON is required}"

wait_seconds="${NETWORK_STABILIZATION_WAIT_SECONDS:-1800}"
poll_seconds="${NETWORK_STABILIZATION_POLL_SECONDS:-15}"
query_timeout_seconds="${NETWORK_STABILIZATION_QUERY_TIMEOUT_SECONDS:-120}"

for value in "$wait_seconds" "$poll_seconds" "$query_timeout_seconds"; do
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "Network stabilization settings must be positive integers." >&2
    exit 1
  fi
done

if ! jq -e '
    type == "array"
    and all(.[];
      (.name | type) == "string"
      and (.requiredDelegations | type) == "array"
      and all(.requiredDelegations[]; type == "string")
    )
  ' <<<"$NETWORK_SUBNET_REQUIREMENTS_JSON" >/dev/null; then
  echo "NETWORK_SUBNET_REQUIREMENTS_JSON is invalid." >&2
  exit 1
fi

deadline=$((SECONDS + wait_seconds))
attempt=0
while [ "$SECONDS" -lt "$deadline" ]; do
  attempt=$((attempt + 1))
  query_rc=0
  vnet_json=$(timeout "${query_timeout_seconds}s" az network vnet show \
    --subscription "$ARM_SUBSCRIPTION_ID" \
    --resource-group "$NETWORK_RESOURCE_GROUP" \
    --name "$NETWORK_VNET_NAME" \
    --output json \
    --only-show-errors 2>&1) || query_rc=$?

  if [ "$query_rc" -ne 0 ]; then
    if [ "$query_rc" -eq 124 ] || [ "$query_rc" -eq 137 ] ||
      echo "$vnet_json" |
      grep -qiE "NotFound|ResourceNotFound|AnotherOperationInProgress|RetryableError|ServerTimeout|ServiceUnavailable|temporarily unavailable|timed out"; then
      echo "[network-wait] attempt=$attempt VNet query not ready: $vnet_json"
      sleep "$poll_seconds"
      continue
    fi
    echo "[network-wait] VNet query failed: $vnet_json" >&2
    exit "$query_rc"
  fi

  if jq -e '
      .provisioningState == "Failed"
      or any(.subnets[]?; .provisioningState == "Failed")
    ' <<<"$vnet_json" >/dev/null; then
    echo "[network-wait] VNet or subnet entered terminal Failed state." >&2
    jq -c '{
      vnetState: .provisioningState,
      failedSubnets: [.subnets[]? | select(.provisioningState == "Failed") | .name]
    }' <<<"$vnet_json" >&2
    exit 1
  fi

  if jq -e --argjson required "$NETWORK_SUBNET_REQUIREMENTS_JSON" '
      . as $vnet
      | $vnet.provisioningState == "Succeeded"
        and all($required[];
          . as $requirement
          | any($vnet.subnets[]?;
              .name == $requirement.name
              and .provisioningState == "Succeeded"
              and all($requirement.requiredDelegations[];
                . as $requiredDelegation
                | any(
                    $vnet.subnets[]
                    | select(.name == $requirement.name)
                    | .delegations[]?;
                    .serviceName == $requiredDelegation
                  )
              )
            )
        )
    ' <<<"$vnet_json" >/dev/null; then
    echo "[network-wait] VNet $NETWORK_VNET_NAME and all required subnets are stable."
    exit 0
  fi

  jq -r --argjson required "$NETWORK_SUBNET_REQUIREMENTS_JSON" '
    . as $vnet
    | [
        $required[]
        | . as $requirement
        | (
            first(
              $vnet.subnets[]?
              | select(.name == $requirement.name)
            ) // {}
          ) as $actual
        | {
            name: $requirement.name,
            state: ($actual.provisioningState // "Missing"),
            missingDelegations: [
              $requirement.requiredDelegations[]
              | select(
                  . as $requiredDelegation
                  | all($actual.delegations[]?; .serviceName != $requiredDelegation)
                )
            ]
          }
        | select(
            .state != "Succeeded"
            or (.missingDelegations | length) > 0
          )
      ] as $pending
    | "[network-wait] vnetState=\($vnet.provisioningState // "Missing") pending=\($pending | tojson)"
  ' <<<"$vnet_json"
  sleep "$poll_seconds"
done

echo "[network-wait] VNet $NETWORK_VNET_NAME did not stabilize within ${wait_seconds}s." >&2
exit 1
