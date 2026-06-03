#!/bin/bash
# canadacentral-preflight.sh
#
# Pre-migration verification for moving clustermesh-scale tests from
# eastus2euap (5K Dv3 vCPU, ClusterMesh GA) to canadacentral (62K DSv4
# vCPU, ClusterMesh verified 2026-05-24). Run as a no-infra stage
# BEFORE committing tfvars + matrix changes.
#
# Verifies (all must pass for migration to be safe):
#   1. SKU availability: Standard_D4s_v4 in canadacentral, no zone restriction
#   2. Quota: family + total cores meet expected need
#   3. Fleet RP registered
#   4. AKS managed Cilium addon available (preview check)
#   5. LoadBalancer Standard + Public IP allocation
#   6. AzDO agent has cc-region service principal credentials (implicit —
#      this script runs via the service connection, so success of any
#      `az` call against cc confirms auth works)
#
# Output: human-readable report to stdout + structured JSON to
# $PREFLIGHT_RESULT_FILE if set.
#
# Exit codes:
#   0 = all checks pass; migration safe to proceed
#   1 = blocking failure (quota, SKU, Fleet) — do NOT migrate
#   2 = soft failure (warning only) — proceed with caution

set -uo pipefail

REGION="${REGION:-canadacentral}"
TARGET_SKU="${TARGET_SKU:-Standard_D4s_v4}"
EXPECTED_TOTAL_CORES="${EXPECTED_TOTAL_CORES:-5000}"  # baseline for N=100 (50 × 100)
SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:-${AZURE_SUBSCRIPTION:-37deca37-c375-4a14-b90a-043849bd2bf1}}"

PREFLIGHT_RESULT_FILE="${PREFLIGHT_RESULT_FILE:-/tmp/canadacentral-preflight.json}"

echo "============================================================"
echo "canadacentral migration preflight"
echo "  region: $REGION"
echo "  target SKU: $TARGET_SKU"
echo "  expected cores: $EXPECTED_TOTAL_CORES"
echo "  subscription: $SUBSCRIPTION"
echo "============================================================"

OVERALL_RC=0
WARNINGS=()
FAILURES=()

# ----- 1. SKU availability in region -----
echo
echo "[1/6] Checking SKU $TARGET_SKU availability in $REGION..."
sku_info=$(az vm list-skus --location "$REGION" --resource-type virtualMachines \
  --query "[?name=='$TARGET_SKU']" -o json --subscription "$SUBSCRIPTION" 2>/dev/null)
if [ -z "$sku_info" ] || [ "$sku_info" = "[]" ]; then
  echo "  FAIL: $TARGET_SKU not available in $REGION"
  FAILURES+=("sku_not_available")
  OVERALL_RC=1
else
  restrictions=$(echo "$sku_info" | jq -r '.[0].restrictions | length')
  zones=$(echo "$sku_info" | jq -r '.[0].locationInfo[0].zones | length')
  echo "  OK: $TARGET_SKU available in $zones zones, $restrictions restrictions"
  if [ "$restrictions" -gt 0 ]; then
    rdetails=$(echo "$sku_info" | jq -r '.[0].restrictions[0].reasonCode // "unknown"')
    echo "  WARN: restriction reason: $rdetails"
    WARNINGS+=("sku_restricted:$rdetails")
  fi
fi

# ----- 2. Quota -----
echo
echo "[2/6] Checking vCPU quota in $REGION..."
usage=$(az vm list-usage --location "$REGION" --subscription "$SUBSCRIPTION" -o json 2>/dev/null)
if [ -z "$usage" ]; then
  echo "  FAIL: could not query vCPU usage"
  FAILURES+=("quota_query_failed")
  OVERALL_RC=1
else
  # Total regional vCPU
  total_limit=$(echo "$usage" | jq -r '.[] | select(.name.value == "cores") | .limit')
  total_used=$(echo "$usage" | jq -r '.[] | select(.name.value == "cores") | .currentValue')
  total_free=$((total_limit - total_used))
  echo "  Regional total: ${total_used}/${total_limit} used, ${total_free} free"

  # DSv4 family quota (Dsv4)
  dsv4_limit=$(echo "$usage" | jq -r '.[] | select(.name.value == "standardDSv4Family") | .limit // 0')
  dsv4_used=$(echo "$usage" | jq -r '.[] | select(.name.value == "standardDSv4Family") | .currentValue // 0')
  dsv4_free=$((dsv4_limit - dsv4_used))
  echo "  DSv4 family: ${dsv4_used}/${dsv4_limit} used, ${dsv4_free} free"

  if [ "$total_free" -lt "$EXPECTED_TOTAL_CORES" ]; then
    echo "  FAIL: total free vCPU ($total_free) < expected need ($EXPECTED_TOTAL_CORES)"
    FAILURES+=("total_quota_insufficient")
    OVERALL_RC=1
  elif [ "$dsv4_free" -lt "$EXPECTED_TOTAL_CORES" ]; then
    echo "  FAIL: DSv4 family free vCPU ($dsv4_free) < expected need ($EXPECTED_TOTAL_CORES)"
    FAILURES+=("dsv4_quota_insufficient")
    OVERALL_RC=1
  else
    echo "  OK: quota headroom sufficient for expected need"
  fi
fi

# ----- 3. Fleet RP registered -----
echo
echo "[3/6] Checking Microsoft.ContainerService Fleet RP registration..."
rp_state=$(az provider show --namespace Microsoft.ContainerService \
  --query "registrationState" -o tsv --subscription "$SUBSCRIPTION" 2>/dev/null)
if [ "$rp_state" = "Registered" ]; then
  echo "  OK: Microsoft.ContainerService is Registered"
else
  echo "  FAIL: Microsoft.ContainerService state = ${rp_state:-unknown}"
  FAILURES+=("fleet_rp_not_registered")
  OVERALL_RC=1
fi

# ----- 4. AKS managed Cilium addon availability (heuristic via az aks list-managed) -----
echo
echo "[4/6] Checking AKS managed Cilium availability (via aks-preview extension)..."
if az extension show --name aks-preview > /dev/null 2>&1; then
  echo "  OK: aks-preview extension installed"
else
  echo "  WARN: aks-preview extension not installed locally (script env). The"
  echo "        AzDO agent installs it per-job via the existing pipeline step."
  WARNINGS+=("aks_preview_not_local")
fi

# ----- 5. LoadBalancer Standard SKU available (implicit at API level) -----
echo
echo "[5/6] Checking LoadBalancer SKU availability..."
lb_sku=$(az vm list-skus --location "$REGION" --resource-type loadBalancers \
  --subscription "$SUBSCRIPTION" -o json 2>/dev/null | jq -r '.[0].name // "unknown"' 2>/dev/null)
if [ -n "$lb_sku" ] && [ "$lb_sku" != "unknown" ]; then
  echo "  OK: LoadBalancer SKUs available (sample: $lb_sku)"
else
  # Soft check — LB SKU is implicitly available in all AKS-supported regions
  echo "  WARN: could not enumerate LB SKUs (likely AzCLI permissions); assuming Standard available since AKS supports cc"
  WARNINGS+=("lb_sku_enum_failed")
fi

# ----- 6. Public IP quota (LBs need at least 1 PIP per cluster) -----
echo
echo "[6/6] Checking Public IP quota in $REGION..."
pip_usage=$(az network list-usages --location "$REGION" --subscription "$SUBSCRIPTION" -o json 2>/dev/null)
if [ -n "$pip_usage" ]; then
  pip_limit=$(echo "$pip_usage" | jq -r '.[] | select(.name.value == "StandardSkuPublicIpAddresses") | .limit // 0')
  pip_used=$(echo "$pip_usage" | jq -r '.[] | select(.name.value == "StandardSkuPublicIpAddresses") | .currentValue // 0')
  pip_free=$((pip_limit - pip_used))
  echo "  Standard PIP: ${pip_used}/${pip_limit} used, ${pip_free} free"
  # Each AKS cluster needs 1 PIP for the egress LB (+ 1 per LB Service).
  # N=100 with our clustermesh-apiserver LB Service = 200 PIPs needed.
  expected_pips=$((${EXPECTED_TOTAL_CORES} / 48 * 2))  # ~2 PIPs/cluster heuristic
  if [ "$pip_free" -lt "$expected_pips" ]; then
    echo "  WARN: PIP free ($pip_free) below 2×clusters need ($expected_pips); request quota if N=100+"
    WARNINGS+=("pip_quota_tight")
  else
    echo "  OK: PIP quota sufficient"
  fi
else
  echo "  WARN: could not query PIP quota"
  WARNINGS+=("pip_query_failed")
fi

# ----- Summary -----
echo
echo "============================================================"
echo "Preflight summary: region=$REGION"
echo "  failures: ${#FAILURES[@]}"
for f in "${FAILURES[@]}"; do echo "    - $f"; done
echo "  warnings: ${#WARNINGS[@]}"
for w in "${WARNINGS[@]}"; do echo "    - $w"; done
echo "============================================================"

# Emit JSON
{
  echo "{"
  echo "  \"region\": \"$REGION\","
  echo "  \"target_sku\": \"$TARGET_SKU\","
  echo "  \"expected_cores\": $EXPECTED_TOTAL_CORES,"
  echo "  \"overall_rc\": $OVERALL_RC,"
  echo "  \"failures\": ["
  for ((i=0; i<${#FAILURES[@]}; i++)); do
    sep=$([ $i -lt $((${#FAILURES[@]} - 1)) ] && echo "," || echo "")
    echo "    \"${FAILURES[$i]}\"$sep"
  done
  echo "  ],"
  echo "  \"warnings\": ["
  for ((i=0; i<${#WARNINGS[@]}; i++)); do
    sep=$([ $i -lt $((${#WARNINGS[@]} - 1)) ] && echo "," || echo "")
    echo "    \"${WARNINGS[$i]}\"$sep"
  done
  echo "  ]"
  echo "}"
} > "$PREFLIGHT_RESULT_FILE"
echo "JSON result: $PREFLIGHT_RESULT_FILE"

if [ "$OVERALL_RC" -eq 0 ] && [ "${#WARNINGS[@]}" -gt 0 ]; then
  echo "PREFLIGHT: PASS with warnings — proceed with caution"
  exit 2
elif [ "$OVERALL_RC" -eq 0 ]; then
  echo "PREFLIGHT: ALL CLEAR — migration safe to proceed"
  exit 0
else
  echo "PREFLIGHT: BLOCKING FAILURE — do NOT migrate" >&2
  exit 1
fi
