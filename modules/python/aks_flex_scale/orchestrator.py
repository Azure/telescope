"""Deterministic Azure/Kubernetes orchestration for the 1,000-node Flex join test."""

from __future__ import annotations

import base64
import concurrent.futures
import fnmatch
import hashlib
import json
import math
import os
import platform
import secrets
import shlex
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .commands import CommandError, az, az_json, json_value, kubectl_json, run, text
from .config import node_names
from .csr import exact_identity
from .state import RunState

AKS_CONTRIBUTOR_ROLE = "ed7f3fbd-7b88-4dd4-9017-9adb7ce333f8"
BLOB_CONTRIBUTOR_ROLE = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
NETWORK_CONTRIBUTOR_ROLE = "4d97b98b-1d4f-4787-a291-c67834d212e7"


def _safe_run_id(value: str) -> str:
    rendered = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    if not rendered:
        raise ValueError("runId must contain letters or digits")
    return rendered[:24]


def runtime_names(config: dict[str, Any]) -> dict[str, str]:
    run_id = _safe_run_id(str(config.get("runId") or os.environ.get("RUN_ID") or f"local-{int(time.time())}"))
    digest = hashlib.sha256(f"{config['subscriptionId']}:{run_id}".encode()).hexdigest()[:12]
    return {
        "runId": run_id,
        "aksResourceGroup": str(config.get("aksResourceGroup") or f"flexscale-{run_id}-aks")[:90],
        "vmResourceGroup": str(config.get("vmResourceGroup") or f"flexscale-{run_id}-vm")[:90],
        "clusterName": str(config.get("clusterName") or f"flexscale-{run_id}")[:63],
        "storageAccount": str(config.get("storageAccount") or f"flexgate{digest}")[:24],
        "gateContainer": str(config.get("gateContainer") or f"run-{run_id}")[:63],
    }


def github_latest(repository: str) -> str:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "telescope-flex-scale"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    tag = value.get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise RuntimeError(f"latest release for {repository} has no tag_name")
    return tag


def resolve_versions(config: dict[str, Any], state: RunState) -> dict[str, str]:
    requested_aks = str(config.get("aksKubernetesVersion", "latest"))
    if requested_aks == "latest":
        versions = az_json("aks", "get-versions", "--subscription", config["subscriptionId"],
                           "--location", config["aksRegion"], timeout=90)
        candidates: list[tuple[int, ...]] = []
        rendered: dict[tuple[int, ...], str] = {}
        for value in versions.get("values", []):
            for version in [value.get("version"), *value.get("patchVersions", {}).keys()]:
                if isinstance(version, str) and "preview" not in version.lower():
                    try:
                        key = tuple(int(part) for part in version.split("."))
                    except ValueError:
                        continue
                    candidates.append(key)
                    rendered[key] = version
        if not candidates:
            raise RuntimeError("no stable AKS version found in the requested region")
        requested_aks = rendered[max(candidates)]
    else:
        regional = az_json("aks", "get-versions", "--subscription", config["subscriptionId"],
                           "--location", config["aksRegion"], timeout=90)
        available = {str(version) for value in regional.get("values", [])
                     for version in [value.get("version"), *value.get("patchVersions", {}).keys()]
                     if version}
        if requested_aks not in available:
            raise RuntimeError(f"AKS version {requested_aks} is unavailable in {config['aksRegion']}")
    flex = str(config.get("aksFlexNodeVersion", "latest"))
    if flex == "latest":
        flex = github_latest(config["bootstrapScriptRepository"])
    unbounded = str(config.get("unboundedVersion", "latest"))
    if unbounded == "latest":
        unbounded = github_latest(config["unboundedRepository"])
    result = {"kubernetes": requested_aks, "aksFlexNode": flex, "unbounded": unbounded}
    state.set_versions(result)
    state.event("versions-resolved", versions=result)
    return result


def plan(config: dict[str, Any], state: RunState) -> dict[str, Any]:
    names = runtime_names(config)
    result = {
        **names,
        "nodeCount": config["nodeCount"],
        "maxPods": config["maxPods"],
        "requiredVcpusMinimum": config["nodeCount"] * 4,
        "vmSku": config["flexVmSize"],
        "regions": {"aks": config["aksRegion"], "vm": config["vmRegion"]},
        "cidrs": {key: config[key] for key in ("aksVnetCidr", "aksSubnetCidr", "flexVnetCidr",
                                                "flexSubnetCidr", "serviceCidr", "aksPodCidr", "flexPodCidr")},
        "joinTimeoutSeconds": config["joinTimeoutSeconds"],
        "successRequirement": "100%",
        "retainOnFailure": config["retainOnFailure"],
    }
    state.data["plan"] = result
    state.save()
    return result


def action_allowed(entries: list[dict[str, Any]], action: str) -> bool:
    target = action.lower()
    for entry in entries:
        actions = [str(item).lower() for item in entry.get("actions", [])]
        excluded = [str(item).lower() for item in entry.get("notActions", [])]
        if (any(fnmatch.fnmatchcase(target, pattern) for pattern in actions)
                and not any(fnmatch.fnmatchcase(target, pattern) for pattern in excluded)):
            return True
    return False


def preflight(config: dict[str, Any], state: RunState) -> dict[str, Any]:
    sub = config["subscriptionId"]
    account = az_json("account", "show", "--subscription", sub)
    if str(account.get("id", "")).lower() != sub.lower() or account.get("state") != "Enabled":
        raise RuntimeError("target Azure subscription is not enabled")
    providers = ("Microsoft.ContainerService", "Microsoft.Compute", "Microsoft.Network",
                 "Microsoft.ManagedIdentity", "Microsoft.Storage", "Microsoft.Authorization")
    bad = []
    for provider in providers:
        value = az_json("provider", "show", "--subscription", sub, "--namespace", provider)
        if value.get("registrationState") != "Registered":
            bad.append(provider)
    if bad:
        raise RuntimeError(f"required providers are not registered: {', '.join(bad)}")
    permissions_url = (f"https://management.azure.com/subscriptions/{sub}/providers/"
                       "Microsoft.Authorization/permissions?api-version=2022-04-01")
    permissions = az_json("rest", "--method", "get", "--url", permissions_url, timeout=60)
    if not action_allowed(permissions.get("value", []), "Microsoft.Authorization/roleAssignments/write"):
        raise RuntimeError("effective Azure permissions do not allow roleAssignments/write")
    skus = az_json("vm", "list-skus", "--subscription", sub, "--location", config["vmRegion"],
                   "--resource-type", "virtualMachines", "--size", config["flexVmSize"], "--all", timeout=120)
    size = next((item for item in skus
                 if item.get("name") == config["flexVmSize"] and not item.get("restrictions")), None)
    if not size:
        raise RuntimeError(f"VM SKU {config['flexVmSize']} is unavailable or restricted in {config['vmRegion']}")
    capabilities = {item.get("name"): item.get("value") for item in size.get("capabilities", [])}
    cores = int(capabilities.get("vCPUs", 0))
    if cores < 4:
        raise RuntimeError(f"VM SKU {config['flexVmSize']} has {cores} cores; at least four are required")
    generations = {item.strip() for item in str(capabilities.get("HyperVGenerations", "")).split(",")}
    if "V2" not in generations:
        raise RuntimeError(
            f"VM SKU {config['flexVmSize']} cannot boot the Ubuntu 24.04 Generation 2 image"
        )
    usage = az_json("vm", "list-usage", "--subscription", sub, "--location", config["vmRegion"], timeout=60)
    total = next((item for item in usage if str(item.get("name", {}).get("value", "")).lower() == "cores"), None)
    required = cores * config["nodeCount"]
    available = int(total.get("limit", 0)) - int(total.get("currentValue", 0)) if total else 0
    if available < required:
        raise RuntimeError(f"regional vCPU quota has {available} available cores; {required} are required")
    family_name = str(size.get("family", "")).lower()
    family = next((item for item in usage
                   if str(item.get("name", {}).get("value", "")).lower() == family_name), None)
    if not family:
        raise RuntimeError(f"could not map SKU {config['flexVmSize']} to its Azure quota family")
    family_available = int(family.get("limit", 0)) - int(family.get("currentValue", 0))
    if family_available < required:
        raise RuntimeError(f"VM-family quota has {family_available} available cores; {required} are required")
    versions = state.data.get("versions") or resolve_versions(config, state)
    rootfs, offline, agent = _bootstrap_urls(config, versions)
    artifact_urls = {
        "bootstrapScript": f"https://raw.githubusercontent.com/{config['bootstrapScriptRepository']}/{versions['aksFlexNode']}/scripts/bootstrap.sh",
        "rootfs": rootfs,
        "offlineBootstrap": offline.replace("{{ .KubernetesVersion }}", f"v{versions['kubernetes'].lstrip('v')}"),
        "agent": agent.replace("{{VERSION}}", versions["aksFlexNode"]).replace(
            "{{ARCHIVE_NAME}}", "aks-flex-node-linux-amd64.tar.gz"),
    }
    for label, url in artifact_urls.items():
        probe = run(["curl", "--location", "--silent", "--show-error", "--fail", "--head", url],
                    timeout=45, check=False)
        if probe.returncode != 0:
            raise RuntimeError(f"required {label} artifact is unavailable: {url}")
    evidence = {"skuCores": cores, "requiredCores": required, "availableRegionalCores": available,
                "availableFamilyCores": family_available, "providers": list(providers),
                "artifacts": list(artifact_urls), "versions": versions}
    state.event("preflight-passed", evidence=evidence)
    return evidence


def _az_exists(args: list[str]) -> bool:
    result = run(["az", *args], timeout=60, check=False)
    return result.returncode == 0


def _wait_feature(sub: str, timeout: int = 1800) -> None:
    value = az_json("feature", "show", "--subscription", sub, "--namespace", "Microsoft.ContainerService",
                    "--name", "PutMachinePreview")
    if value.get("properties", {}).get("state") != "Registered":
        az("feature", "register", "--subscription", sub, "--namespace", "Microsoft.ContainerService",
           "--name", "PutMachinePreview")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = az_json("feature", "show", "--subscription", sub, "--namespace", "Microsoft.ContainerService",
                            "--name", "PutMachinePreview")
            if value.get("properties", {}).get("state") == "Registered":
                az("provider", "register", "--subscription", sub, "--namespace", "Microsoft.ContainerService")
                return
            time.sleep(20)
        raise TimeoutError("PutMachinePreview did not register before its deadline")


def _apply_yaml(documents: list[dict[str, Any]]) -> None:
    # JSON is valid YAML; separate documents allow kubectl to consume multiple objects.
    payload = b"\n---\n".join(json.dumps(item).encode() for item in documents)
    result = run(["kubectl", "apply", "--server-side", "-f", "-"], input_bytes=payload, timeout=120, check=False)
    if result.returncode != 0:
        raise CommandError(["kubectl", "apply"], result.returncode, result.stderr.decode("utf-8", "replace"))


def _install_unbounded(config: dict[str, Any], versions: dict[str, str]) -> None:
    arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    if not arch:
        raise RuntimeError(f"unsupported workstation architecture: {platform.machine()}")
    tag = versions["unbounded"]
    url = f"https://github.com/{config['unboundedRepository']}/releases/download/{tag}/kubectl-unbounded-linux-{arch}.tar.gz"
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "plugin.tar.gz"
        urllib.request.urlretrieve(url, archive)
        run(["tar", "-xzf", str(archive), "-C", directory], timeout=60)
        plugin = next(Path(directory).rglob("kubectl-unbounded"), None)
        if not plugin:
            raise RuntimeError("kubectl-unbounded was not present in the release archive")
        endpoint = az("aks", "show", "--subscription", config["subscriptionId"], "--resource-group",
                      runtime_names(config)["aksResourceGroup"], "--name", runtime_names(config)["clusterName"],
                      "--query", "fqdn", "--output", "tsv")
        run([str(plugin), "install", "--api-server-endpoint", f"https://{endpoint}:443", "--wait",
             "--timeout", "5m"], timeout=600)

    _apply_yaml([
        {"apiVersion": "unbounded-cloud.io/v1alpha3", "kind": "Site", "metadata": {"name": "cluster"},
         "spec": {"components": {"machina": {"enabled": True}}, "manageCniPlugin": True,
                  "nodeCidrs": [config["aksVnetCidr"]],
                  "podCidrAssignments": [{"cidrBlocks": [config["aksPodCidr"]]}]}},
        {"apiVersion": "unbounded-cloud.io/v1alpha3", "kind": "Site", "metadata": {"name": "flex-site"},
         "spec": {"manageCniPlugin": True, "nodeCidrs": [config["flexVnetCidr"]],
                  "podCidrAssignments": [{"cidrBlocks": [config["flexPodCidr"]]}]}},
        {"apiVersion": "net.unbounded-cloud.io/v1alpha1", "kind": "SitePeering",
         "metadata": {"name": "cluster-flex-private-l3"},
         "spec": {"sites": ["cluster", "flex-site"], "meshNodes": True, "tunnelProtocol": "Auto"}},
    ])
    for resource in ("deployment/unbounded-operator", "deployment/unbounded-net-controller",
                     "daemonset/unbounded-net-node", "deployment/machina-controller"):
        run(["kubectl", "-n", "unbounded-system", "rollout", "status", resource, "--timeout=10m"], timeout=660)
    for resource in ("gatewaypools", "sitegatewaypoolassignments"):
        value = kubectl_json("get", resource)
        if value.get("items"):
            raise RuntimeError(f"unexpected {resource} exist in the direct VNet topology")


def _put_role_assignment(subscription: str, principal_id: str, scope: str, role_id: str,
                         principal_type: str = "ServicePrincipal") -> None:
    assignment_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope.lower()}:{principal_id.lower()}:{role_id}"))
    url = (f"https://management.azure.com{scope}/providers/Microsoft.Authorization/roleAssignments/"
           f"{assignment_id}?api-version=2022-04-01")
    body = {"properties": {
        "roleDefinitionId": f"/subscriptions/{subscription}/providers/Microsoft.Authorization/roleDefinitions/{role_id}",
        "principalId": principal_id,
        "principalType": principal_type,
    }}
    az("rest", "--method", "put", "--url", url, "--body", json.dumps(body), timeout=120)


def _current_azure_principal() -> tuple[str, str]:
    """Return the current token's object ID and ARM principal type without Graph."""
    token = az("account", "get-access-token", "--resource", "https://management.azure.com/",
               "--query", "accessToken", "--output", "tsv")
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("could not decode the current ARM token claims") from exc
    object_id = str(claims.get("oid", ""))
    if not object_id:
        raise RuntimeError("current ARM token has no oid claim")
    principal_type = "ServicePrincipal" if claims.get("idtyp") == "app" else "User"
    return object_id, principal_type


def _create_aks_arm(config: dict[str, Any], names: dict[str, str], versions: dict[str, str],
                    subnet_id: str) -> None:
    """Create AKS through ARM, avoiding local Azure CLI SDK/version coupling."""
    sub = config["subscriptionId"]
    identity_name = f"{names['clusterName']}-control-plane"[:128]
    identity = az_json("identity", "create", "--subscription", sub, "--resource-group",
                       names["aksResourceGroup"], "--name", identity_name, "--location", config["aksRegion"])
    _put_role_assignment(sub, identity["principalId"], subnet_id, NETWORK_CONTRIBUTOR_ROLE)
    public_key_path = Path.home() / ".ssh" / "id_rsa.pub"
    if not public_key_path.exists():
        private_key = Path.home() / ".ssh" / "id_rsa"
        private_key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        run(["ssh-keygen", "-q", "-t", "rsa", "-b", "3072", "-N", "", "-f", str(private_key)])
    public_key = public_key_path.read_text(encoding="utf-8").strip()
    identity_id = identity["id"]
    body = {
        "location": config["aksRegion"],
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity_id: {}}},
        "sku": {"name": "Base", "tier": "Standard"},
        "tags": {"telescope-run-id": names["runId"], "SkipAKSCluster": "true",
                 "SkipASMAzSecPackAutoConfig": "true", "SkipLinuxAzSecPack": "true"},
        "properties": {
            "dnsPrefix": f"{names['clusterName']}-dns"[:54],
            "kubernetesVersion": versions["kubernetes"],
            "enableRBAC": True,
            "linuxProfile": {"adminUsername": config["vmAdminUser"],
                             "ssh": {"publicKeys": [{"keyData": public_key}]}},
            "agentPoolProfiles": [{
                "name": config["aksSystemPoolName"], "mode": "System", "count": 3,
                "vmSize": config["aksNodeVmSize"], "osType": "Linux", "osSKU": "Ubuntu",
                "type": "VirtualMachineScaleSets", "vnetSubnetID": subnet_id, "maxPods": 110,
            }],
            "networkProfile": {
                "networkPlugin": "none", "podCidr": config["aksPodCidr"],
                "serviceCidr": config["serviceCidr"], "dnsServiceIP": config["dnsServiceIp"],
                "loadBalancerSku": "standard", "outboundType": "loadBalancer",
            },
            "apiServerAccessProfile": {"enablePrivateCluster": False},
        },
    }
    cluster_id = (f"/subscriptions/{sub}/resourceGroups/{names['aksResourceGroup']}"
                  f"/providers/Microsoft.ContainerService/managedClusters/{names['clusterName']}")
    url = f"https://management.azure.com{cluster_id}?api-version={config['managedClusterApiVersion']}"
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            az("rest", "--method", "put", "--url", url, "--body", json.dumps(body), timeout=300)
            last_error = None
            break
        except CommandError as exc:
            last_error = exc
            if attempt == 5:
                raise
            time.sleep(30)
    if last_error:
        raise last_error
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        cluster = az_json("rest", "--method", "get", "--url", url, timeout=90)
        status = cluster.get("properties", {}).get("provisioningState")
        if status == "Succeeded":
            return
        if status in {"Failed", "Canceled"}:
            raise RuntimeError(f"AKS ARM provisioning entered terminal state {status}")
        time.sleep(20)
    raise TimeoutError("AKS cluster did not become Succeeded within one hour")


def _ensure_flex_daemon_rbac() -> None:
    """Apply the narrowly scoped temporary daemon RBAC used before regional RP rollout."""
    _apply_yaml([
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
         "metadata": {"name": "aks-flex-node-daemon"},
         "rules": [
             {"apiGroups": ["unbounded-cloud.io"],
              "resources": ["machines", "machines/status", "machineoperations", "machineoperations/status"],
              "verbs": ["get", "list", "watch", "create", "update", "patch"]},
             {"apiGroups": [""], "resources": ["nodes"], "verbs": ["get", "list", "watch"]},
         ]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
         "metadata": {"name": "aks-flex-node-daemon"},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole",
                     "name": "aks-flex-node-daemon"},
         "subjects": [{"apiGroup": "rbac.authorization.k8s.io", "kind": "Group",
                       "name": "aks-flex-node-daemons"}]},
    ])


def _setup_local_bootstrap_rbac() -> None:
    _apply_yaml([
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
         "metadata": {"name": "aks-flex-node-bootstrapper"},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole",
                     "name": "system:node-bootstrapper"},
         "subjects": [{"apiGroup": "rbac.authorization.k8s.io", "kind": "Group",
                       "name": "system:bootstrappers:aks-flex-node"}]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
         "metadata": {"name": "aks-flex-node-auto-approve-csr"},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole",
                     "name": "system:certificates.k8s.io:certificatesigningrequests:nodeclient"},
         "subjects": [{"apiGroup": "rbac.authorization.k8s.io", "kind": "Group",
                       "name": "system:bootstrappers:aks-flex-node"}]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
         "metadata": {"name": "aks-flex-node-role"},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole",
                     "name": "system:node"},
         "subjects": [{"apiGroup": "rbac.authorization.k8s.io", "kind": "Group",
                       "name": "system:bootstrappers:aks-flex-node"}]},
    ])


def _prepare_local_bootstrap_config(config: dict[str, Any], state: RunState) -> None:
    """Generate a run-scoped bootstrap-token config without listBootstrapData."""
    _setup_local_bootstrap_rbac()
    names = runtime_names(config)
    resources = state.data["resources"]
    versions = state.data["versions"]
    token_id = secrets.token_hex(3)
    token_secret = secrets.token_hex(8)
    token = f"{token_id}.{token_secret}"
    expiration = (datetime.now(timezone.utc) + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _apply_yaml([{
        "apiVersion": "v1", "kind": "Secret", "type": "bootstrap.kubernetes.io/token",
        "metadata": {"name": f"bootstrap-token-{token_id}", "namespace": "kube-system",
                     "labels": {"telescope-run-id": names["runId"]}},
        "stringData": {"description": "AKS Flex scale-test bootstrap token", "token-id": token_id,
                       "token-secret": token_secret, "expiration": expiration,
                       "usage-bootstrap-authentication": "true", "usage-bootstrap-signing": "true",
                       "auth-extra-groups": "system:bootstrappers:aks-flex-node"},
    }])
    kubeconfig = kubectl_json("config", "view", "--minify", "--raw")
    clusters = kubeconfig.get("clusters", [])
    if not clusters:
        raise RuntimeError("current kubeconfig has no cluster for local bootstrap config")
    cluster = clusters[0].get("cluster", {})
    server = str(cluster.get("server", ""))
    ca_data = str(cluster.get("certificate-authority-data", ""))
    fqdn = urlsplit(server).netloc or server
    if not fqdn or not ca_data:
        raise RuntimeError("current kubeconfig lacks API server or CA data")
    account = az_json("account", "show", "--subscription", config["subscriptionId"])
    rootfs, offline, _ = _bootstrap_urls(config, versions)
    base_config = {
        "azure": {
            "subscriptionId": config["subscriptionId"], "tenantId": account["tenantId"],
            "resourceManagerEndpoint": "https://management.azure.com",
            "targetAgentPoolName": config["agentPoolName"],
            "bootstrapToken": {"token": token},
            "managedIdentity": {"clientId": resources["identityClientId"]},
            "arc": {"enabled": False},
            "targetCluster": {"resourceId": resources["clusterId"], "location": config["aksRegion"]},
        },
        # Confirmed in AKSFlexNode EnsureMachine: false logs the RP Machine error
        # and continues local bootstrap instead of failing the node start.
        "agent": {"logLevel": "info", "logDir": "/var/log/aks-flex-node",
                  "requireMachineRegistration": False},
        "components": {"kubernetes": versions["kubernetes"]},
        "bootstrap": {"ociImage": rootfs, "offlineArtifacts": {"source": offline}},
        "networking": {"dnsServiceIP": config["dnsServiceIp"]},
        "node": {"maxPods": config["maxPods"],
                 "kubelet": {"clusterFQDN": fqdn, "caCertData": ca_data}},
    }
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as handle:
        json.dump(base_config, handle)
        handle.flush()
        az("storage", "blob", "upload", "--account-name", names["storageAccount"],
           "--auth-mode", "login", "--container-name", names["gateContainer"],
           "--name", "config/base.json", "--file", handle.name, "--overwrite")
    state.event("local-bootstrap-config-ready", expiresAt=expiration)


def _delete_local_bootstrap_material(config: dict[str, Any]) -> None:
    if config.get("bootstrapMode") != "local-config":
        return
    names = runtime_names(config)
    run(["kubectl", "-n", "kube-system", "delete", "secret", "-l",
         f"telescope-run-id={names['runId']}", "--ignore-not-found=true"], timeout=60, check=False)
    run(["az", "storage", "blob", "delete", "--account-name", names["storageAccount"],
         "--auth-mode", "login", "--container-name", names["gateContainer"],
         "--name", "config/base.json"], timeout=60, check=False)


def provision_environment(config: dict[str, Any], state: RunState) -> dict[str, Any]:
    names = runtime_names(config)
    versions = state.data.get("versions") or resolve_versions(config, state)
    sub = config["subscriptionId"]
    tags = f"telescope-run-id={names['runId']} telescope-scenario=aks-flex-scale"
    for group, region in ((names["aksResourceGroup"], config["aksRegion"]),
                          (names["vmResourceGroup"], config["vmRegion"])):
        az("group", "create", "--subscription", sub, "--name", group, "--location", region,
           "--tags", *tags.split())
    az("network", "vnet", "create", "--subscription", sub, "--resource-group", names["aksResourceGroup"],
       "--name", config["aksVnetName"], "--address-prefixes", config["aksVnetCidr"],
       "--subnet-name", config["aksSubnetName"], "--subnet-prefixes", config["aksSubnetCidr"])
    az("network", "vnet", "create", "--subscription", sub, "--resource-group", names["vmResourceGroup"],
       "--name", config["flexVnetName"], "--address-prefixes", config["flexVnetCidr"],
       "--subnet-name", config["flexSubnetName"], "--subnet-prefixes", config["flexSubnetCidr"])
    aks_vnet = az("network", "vnet", "show", "--subscription", sub, "--resource-group", names["aksResourceGroup"],
                  "--name", config["aksVnetName"], "--query", "id", "--output", "tsv")
    flex_vnet = az("network", "vnet", "show", "--subscription", sub, "--resource-group", names["vmResourceGroup"],
                   "--name", config["flexVnetName"], "--query", "id", "--output", "tsv")
    flex_subnet = az("network", "vnet", "subnet", "show", "--subscription", sub, "--resource-group",
                     names["vmResourceGroup"], "--vnet-name", config["flexVnetName"], "--name",
                     config["flexSubnetName"], "--query", "id", "--output", "tsv")
    # Flex VMs remain private but need scalable outbound access for packages and
    # release artifacts before they join. A /28 prefix avoids one-IP SNAT pressure.
    prefix_name = "flex-egress-prefix"
    nat_name = "flex-egress-nat"
    prefix = az_json("network", "public-ip", "prefix", "create", "--subscription", sub,
                     "--resource-group", names["vmResourceGroup"], "--name", prefix_name,
                     "--location", config["vmRegion"], "--length", "28", "--sku", "Standard")
    prefix_id = prefix.get("publicIpPrefix", {}).get("id") or prefix.get("id")
    if not prefix_id:
        prefix_id = az("network", "public-ip", "prefix", "show", "--subscription", sub,
                       "--resource-group", names["vmResourceGroup"], "--name", prefix_name,
                       "--query", "id", "--output", "tsv")
    nat = az_json("network", "nat", "gateway", "create", "--subscription", sub,
                  "--resource-group", names["vmResourceGroup"], "--name", nat_name,
                  "--location", config["vmRegion"], "--public-ip-prefixes", prefix_id,
                  "--idle-timeout", "10")
    nat_id = nat.get("id") or nat.get("natGateway", {}).get("id")
    if not nat_id:
        nat_id = az("network", "nat", "gateway", "show", "--subscription", sub,
                    "--resource-group", names["vmResourceGroup"], "--name", nat_name,
                    "--query", "id", "--output", "tsv")
    nsg = az_json("network", "nsg", "create", "--subscription", sub, "--resource-group",
                  names["vmResourceGroup"], "--name", "flex-shared-nsg", "--location", config["vmRegion"])
    nsg_id = nsg.get("NewNSG", {}).get("id") or nsg.get("id")
    if not nsg_id:
        nsg_id = az("network", "nsg", "show", "--subscription", sub, "--resource-group",
                    names["vmResourceGroup"], "--name", "flex-shared-nsg", "--query", "id", "--output", "tsv")
    az("network", "vnet", "subnet", "update", "--subscription", sub, "--resource-group",
       names["vmResourceGroup"], "--vnet-name", config["flexVnetName"], "--name",
       config["flexSubnetName"], "--nat-gateway", nat_id, "--network-security-group", nsg_id)
    az("network", "vnet", "peering", "create", "--subscription", sub, "--resource-group", names["aksResourceGroup"],
       "--vnet-name", config["aksVnetName"], "--name", "aks-to-flex", "--remote-vnet", flex_vnet,
       "--allow-vnet-access", "--allow-forwarded-traffic")
    az("network", "vnet", "peering", "create", "--subscription", sub, "--resource-group", names["vmResourceGroup"],
       "--vnet-name", config["flexVnetName"], "--name", "flex-to-aks", "--remote-vnet", aks_vnet,
       "--allow-vnet-access", "--allow-forwarded-traffic")
    aks_subnet = az("network", "vnet", "subnet", "show", "--subscription", sub, "--resource-group",
                    names["aksResourceGroup"], "--vnet-name", config["aksVnetName"], "--name",
                    config["aksSubnetName"], "--query", "id", "--output", "tsv")
    if not _az_exists(["aks", "show", "--subscription", sub, "--resource-group", names["aksResourceGroup"],
                       "--name", names["clusterName"]]):
        _create_aks_arm(config, names, versions, aks_subnet)
    az("aks", "get-credentials", "--subscription", sub, "--resource-group", names["aksResourceGroup"],
       "--name", names["clusterName"], "--admin", "--overwrite-existing")
    _install_unbounded(config, versions)
    _ensure_flex_daemon_rbac()
    _wait_feature(sub)
    identity = az_json("identity", "create", "--subscription", sub, "--resource-group", names["vmResourceGroup"],
                       "--name", config["sharedIdentityName"], "--location", config["vmRegion"])
    cluster_id = az("aks", "show", "--subscription", sub, "--resource-group", names["aksResourceGroup"],
                    "--name", names["clusterName"], "--query", "id", "--output", "tsv")
    # Object-ID based deterministic ARM PUT avoids Microsoft Graph lookup.
    _put_role_assignment(sub, identity["principalId"], cluster_id, AKS_CONTRIBUTOR_ROLE)
    body = {"properties": {"type": "FlexNodes", "mode": "User", "maxPods": config["maxPods"],
                           "orchestratorVersion": versions["kubernetes"]}}
    pool_url = f"https://management.azure.com{cluster_id}/agentPools/{config['agentPoolName']}?api-version={config['bootstrapDataApiVersion']}"
    az("rest", "--method", "put", "--url", pool_url, "--body", json.dumps(body), timeout=900)
    pool_deadline = time.monotonic() + 1800
    while time.monotonic() < pool_deadline:
        pool = az_json("rest", "--method", "get", "--url", pool_url, timeout=90)
        state_value = pool.get("properties", {}).get("provisioningState")
        if state_value == "Succeeded":
            break
        if state_value == "Failed":
            raise RuntimeError("FlexNodes pool provisioning failed")
        time.sleep(15)
    else:
        raise TimeoutError("FlexNodes pool did not become Succeeded")
    storage = az_json("storage", "account", "create", "--subscription", sub, "--resource-group",
                      names["vmResourceGroup"], "--name", names["storageAccount"], "--location", config["vmRegion"],
                      "--sku", "Standard_LRS", "--kind", "StorageV2", "--allow-blob-public-access", "false",
                      "--min-tls-version", "TLS1_2", "--https-only", "true")
    _create_private_gate_container(config, names, storage["id"])
    _put_role_assignment(sub, identity["principalId"], storage["id"], BLOB_CONTRIBUTOR_ROLE)
    controller_id, controller_type = _current_azure_principal()
    _put_role_assignment(sub, controller_id, storage["id"], BLOB_CONTRIBUTOR_ROLE, controller_type)
    _verify_private_gate_storage(config, names, storage)
    resources = {**names, "clusterId": cluster_id, "flexSubnetId": flex_subnet,
                 "identityId": identity["id"], "identityClientId": identity["clientId"],
                 "storageId": storage["id"]}
    state.data["resources"].update(resources)
    state.save()
    if config.get("bootstrapMode") == "local-config":
        _prepare_local_bootstrap_config(config, state)
    state.event("environment-ready", resources={key: value for key, value in resources.items() if "key" not in key.lower()})
    return resources


def _create_private_gate_container(config: dict[str, Any], names: dict[str, str], storage_id: str) -> None:
    """Create a normal private container through ARM; never create/use $web."""
    container = names["gateContainer"]
    if container.lower() == "$web":
        raise ValueError("the static website $web container is forbidden")
    url = (f"https://management.azure.com{storage_id}/blobServices/default/containers/{container}"
           "?api-version=2023-05-01")
    az("rest", "--method", "put", "--url", url,
       "--body", json.dumps({"properties": {"publicAccess": "None"}}), timeout=120)
    value = az_json("rest", "--method", "get", "--url", url, timeout=60)
    public_access = value.get("properties", {}).get("publicAccess")
    if public_access not in (None, "None"):
        raise RuntimeError(f"gate container unexpectedly permits public access: {public_access}")


def _verify_private_gate_storage(config: dict[str, Any], names: dict[str, str], storage: dict[str, Any]) -> None:
    if storage.get("allowBlobPublicAccess") is not False:
        raise RuntimeError("gate storage account must have allowBlobPublicAccess=false")
    deadline = time.monotonic() + 600
    while True:
        try:
            properties = az_json("storage", "blob", "service-properties", "show", "--account-name",
                                 names["storageAccount"], "--auth-mode", "login", timeout=60)
            containers = az_json("storage", "container", "list", "--account-name", names["storageAccount"],
                                 "--auth-mode", "login", timeout=60)
            break
        except CommandError:
            if time.monotonic() >= deadline:
                raise TimeoutError("controller Blob RBAC did not propagate within ten minutes")
            time.sleep(10)
    if properties.get("staticWebsite", {}).get("enabled") is True:
        raise RuntimeError("static website hosting must remain disabled on gate storage")
    if any(str(item.get("name", "")).lower() == "$web" for item in containers):
        raise RuntimeError("the gate storage account must not contain a $web container")


def _bootstrap_urls(config: dict[str, Any], versions: dict[str, str]) -> tuple[str, str, str]:
    endpoint = config["centralArtifactsEndpoint"].rstrip("/")
    rootfs = str(config.get("bootstrapOciImage") or
                 f"{endpoint}/releases/{versions['unbounded']}/rootfs/{config['bootstrapRootfsName']}")
    offline = str(config.get("bootstrapOfflineArtifactsSource") or
                   f"{endpoint}/releases/{versions['unbounded']}/bootstrap-artifacts/bootstrap-artifacts-k8s-{{{{ .KubernetesVersion }}}}.tar.gz")
    # Follow AKSFlexNode operator-first-boot: fetch the agent from the same
    # IPv6-capable Azure Front Door endpoint as rootfs/bootstrap artifacts.
    agent = str(config.get("agentUrl") or
                f"{endpoint}/releases/aks-flex-node/{{{{VERSION}}}}/{{{{ARCHIVE_NAME}}}}")
    return rootfs, offline, agent


def render_cloud_init(config: dict[str, Any], state: RunState, node: str) -> str:
    resources = state.data["resources"]
    versions = state.data["versions"]
    names = runtime_names(config)
    rootfs, offline, agent = _bootstrap_urls(config, versions)
    gate_base = f"https://{names['storageAccount']}.blob.core.windows.net/{names['gateContainer']}"
    bootstrap_url = f"https://raw.githubusercontent.com/{config['bootstrapScriptRepository']}/{versions['aksFlexNode']}/scripts/bootstrap.sh"
    if config.get("bootstrapMode") == "local-config":
        command = ["/usr/local/bin/aks-flex-node", "start", "--config", "/etc/aks-flex-node/config.json"]
    else:
        command = [
            "bash", "/opt/aks-flex-scale/bootstrap.sh", "--auth", "msi", "--msi-client-id",
            resources["identityClientId"], "--fetch-bootstrap-data", "--cluster-resource-id", resources["clusterId"],
            "--agent-pool-name", config["agentPoolName"], "--bootstrap-data-api-version", config["bootstrapDataApiVersion"],
            "--agent-version", versions["aksFlexNode"], "--bootstrap-oci-image", rootfs,
            "--bootstrap-offline-artifacts-source", offline, "--agent-url", agent,
        ]
    shell_command = " \\\n  ".join(shlex.quote(str(item)) for item in command)
    watcher = f'''#!/usr/bin/env bash
set -euo pipefail
umask 077
base={shlex.quote(gate_base)}
node={shlex.quote(node)}
token() {{ curl -fsS -H Metadata:true "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2019-08-01&resource=https%3A%2F%2Fstorage.azure.com%2F&client_id={resources['identityClientId']}" | jq -r .access_token; }}
put_marker() {{ local name="$1" access; for _ in $(seq 1 60); do access=$(token) && curl -fsS -X PUT -H "Authorization: Bearer $access" -H 'x-ms-version: 2023-11-03' -H 'x-ms-blob-type: BlockBlob' --data-binary '' "$base/$name" >/dev/null && return 0; sleep 10; done; return 1; }}
put_marker "prepared/$node"
while true; do
  access=$(token)
  code=$(curl -sS -o /dev/null -w '%{{http_code}}' -H "Authorization: Bearer $access" -H 'x-ms-version: 2023-11-03' "$base/start")
  if [ "$code" = 200 ]; then break; fi
  if [ "$code" != 404 ]; then echo "gate returned HTTP $code" >&2; fi
  sleep $((2 + RANDOM % 4))
done
date -u +%FT%TZ > /var/lib/aks-flex-scale-triggered
put_marker "triggered/$node"
# AKSFlexNode creates nspawn rootfs paths during start. A restrictive inherited
# umask makes those paths non-traversable by dbus and other non-root services.
# The upstream operator-first-boot guide explicitly requires umask 022 here.
umask 022
if ! {shell_command}; then
  put_marker "failed/$node"
  exit 1
fi
put_marker "bootstrap-completed/$node"
'''
    common_prepare = '''#!/usr/bin/env bash
set -euo pipefail
umask 077
export DEBIAN_FRONTEND=noninteractive
for attempt in $(seq 1 6); do
  if apt-get update && apt-get install -y bash ca-certificates curl jq nftables systemd-container tar util-linux; then
    break
  fi
  if [ "$attempt" = 6 ]; then exit 1; fi
  sleep $((attempt * 10))
done
install -d -m 0700 /opt/aks-flex-scale
# systemd-container package installation may create this under the preparation
# script's restrictive umask; nspawn rootfs ancestry must remain traversable.
install -d -m 0755 /var/lib/machines
'''
    if config.get("bootstrapMode") == "local-config":
        agent_url = (agent.replace("{{VERSION}}", versions["aksFlexNode"])
                     .replace("{{ARCHIVE_NAME}}", "aks-flex-node-linux-amd64.tar.gz"))
        mode_prepare = f'''install -d -m 0755 /etc/aks-flex-node
access=$(curl -fsS -H Metadata:true "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2019-08-01&resource=https%3A%2F%2Fstorage.azure.com%2F&client_id={resources['identityClientId']}" | jq -r .access_token)
curl --connect-timeout 20 --max-time 180 --retry 3 --retry-all-errors -fsS \\
  -H "Authorization: Bearer $access" -H 'x-ms-version: 2023-11-03' \\
  {shlex.quote(gate_base + '/config/base.json')} -o /run/aks-flex-base-config.json
node_ip=$(curl -fsS -H Metadata:true 'http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/privateIpAddress?api-version=2021-02-01&format=text')
jq --arg node {shlex.quote(node)} --arg nodeIP "$node_ip" \\
  '.agent.nodeName = $node | .node.kubelet.nodeIP = $nodeIP' \\
  /run/aks-flex-base-config.json > /run/aks-flex-node-config.json
install -m 0600 /run/aks-flex-node-config.json /etc/aks-flex-node/config.json
rm -f /run/aks-flex-base-config.json /run/aks-flex-node-config.json
curl --connect-timeout 20 --max-time 180 --retry 3 --retry-all-errors -fsSLo /run/aks-flex-node-agent.tgz {shlex.quote(agent_url)}
tar -xzf /run/aks-flex-node-agent.tgz -C /run
install -m 0755 /run/aks-flex-node-linux-amd64 /usr/local/bin/aks-flex-node
rm -f /run/aks-flex-node-agent.tgz /run/aks-flex-node-linux-amd64
/usr/local/bin/aks-flex-node preflight --config /etc/aks-flex-node/config.json --output text
'''
    else:
        mode_prepare = f'''for attempt in $(seq 1 6); do
  if curl --connect-timeout 20 --max-time 180 --retry 3 --retry-all-errors -fsSLo /opt/aks-flex-scale/bootstrap.sh {shlex.quote(bootstrap_url)}; then
    break
  fi
  if [ "$attempt" = 6 ]; then exit 1; fi
  sleep $((attempt * 10))
done
chmod 0700 /opt/aks-flex-scale/bootstrap.sh
bash -n /opt/aks-flex-scale/bootstrap.sh
'''
    prepare = common_prepare + mode_prepare + '''systemctl daemon-reload
systemctl enable --now aks-flex-scale-gate.service
'''
    indented = "\n".join("      " + line for line in watcher.splitlines())
    prepare_indented = "\n".join("      " + line for line in prepare.splitlines())
    return f'''#cloud-config
runcmd:
  - [bash, /usr/local/sbin/aks-flex-scale-prepare]
write_files:
  - path: /etc/systemd/system/aks-flex-scale-gate.service
    owner: root:root
    permissions: '0644'
    content: |
      [Unit]
      Description=AKS Flex scale join gate
      After=network-online.target
      Wants=network-online.target
      [Service]
      Type=oneshot
      ExecStart=/usr/local/sbin/aks-flex-scale-gate
      RemainAfterExit=yes
      [Install]
      WantedBy=multi-user.target
  - path: /usr/local/sbin/aks-flex-scale-gate
    owner: root:root
    permissions: '0700'
    content: |
{indented}
  - path: /usr/local/sbin/aks-flex-scale-prepare
    owner: root:root
    permissions: '0700'
    content: |
{prepare_indented}
'''


def _vm_batch_template(config: dict[str, Any], state: RunState, nodes: list[str],
                       ssh_public_key: str) -> dict[str, Any]:
    image_parts = str(config["vmImage"]).split(":")
    if len(image_parts) != 4:
        raise ValueError("vmImage must be publisher:offer:sku:version for ARM batch deployment")
    publisher, offer, sku, version = image_parts
    resources: list[dict[str, Any]] = []
    subnet_id = state.data["resources"]["flexSubnetId"]
    identity_id = state.data["resources"]["identityId"]
    for node in nodes:
        nic_name = f"{node}-nic"
        nic_resource_id = f"[resourceId('Microsoft.Network/networkInterfaces', '{nic_name}')]"
        resources.append({
            "type": "Microsoft.Network/networkInterfaces", "apiVersion": "2024-05-01",
            "name": nic_name, "location": config["vmRegion"],
            "tags": {"telescope-run-id": runtime_names(config)["runId"], "telescope-node": node},
            "properties": {"ipConfigurations": [{"name": "ipconfig1", "properties": {
                "privateIPAllocationMethod": "Dynamic", "subnet": {"id": subnet_id},
            }}]},
        })
        custom_data = base64.b64encode(render_cloud_init(config, state, node).encode()).decode()
        resources.append({
            "type": "Microsoft.Compute/virtualMachines", "apiVersion": "2024-07-01",
            "name": node, "location": config["vmRegion"],
            "dependsOn": [nic_resource_id],
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {identity_id: {}}},
            "tags": {"telescope-run-id": runtime_names(config)["runId"], "telescope-node": node},
            "properties": {
                "hardwareProfile": {"vmSize": config["flexVmSize"]},
                "storageProfile": {
                    "imageReference": {"publisher": publisher, "offer": offer, "sku": sku, "version": version},
                    "osDisk": {"createOption": "FromImage", "diskSizeGB": config["vmOsDiskSizeGb"],
                               "deleteOption": "Delete",
                               "managedDisk": {"storageAccountType": "StandardSSD_LRS"}},
                },
                "osProfile": {
                    "computerName": node, "adminUsername": config["vmAdminUser"], "customData": custom_data,
                    "linuxConfiguration": {"disablePasswordAuthentication": True, "ssh": {"publicKeys": [{
                        "path": f"/home/{config['vmAdminUser']}/.ssh/authorized_keys", "keyData": ssh_public_key,
                    }]}},
                },
                "networkProfile": {"networkInterfaces": [{"id": nic_resource_id,
                                                            "properties": {"primary": True,
                                                                           "deleteOption": "Delete"}}]},
                "diagnosticsProfile": {"bootDiagnostics": {"enabled": True}},
            },
        })
    return {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0", "resources": resources}


def _deploy_vm_batch(config: dict[str, Any], state: RunState, nodes: list[str],
                     template_dir: Path, ssh_public_key: str) -> None:
    names = runtime_names(config)
    deployment_name = f"flex-vms-{nodes[0].rsplit('-', 1)[-1]}-{nodes[-1].rsplit('-', 1)[-1]}"
    template_path = template_dir / f"{deployment_name}.json"
    template_path.write_text(json.dumps(_vm_batch_template(config, state, nodes, ssh_public_key)),
                             encoding="utf-8")
    # One attempt by design: a failed batch aborts and the run VM resource group is deleted.
    run(["az", "deployment", "group", "create", "--subscription", config["subscriptionId"],
         "--resource-group", names["vmResourceGroup"], "--name", deployment_name,
         "--mode", "Incremental", "--template-file", str(template_path), "--output", "none"],
        timeout=3600, attempts=1)
    state.nodes_event("vm-provisioned", nodes, deployment=deployment_name)


def _delete_failed_vm_run(config: dict[str, Any], state: RunState, reason: str) -> None:
    names = runtime_names(config)
    _delete_local_bootstrap_material(config)
    run(["az", "network", "vnet", "peering", "delete", "--subscription", config["subscriptionId"],
         "--resource-group", names["aksResourceGroup"], "--vnet-name", config["aksVnetName"],
         "--name", "aks-to-flex"], timeout=120, check=False)
    run(["az", "group", "delete", "--subscription", config["subscriptionId"],
         "--name", names["vmResourceGroup"], "--yes", "--no-wait"], timeout=120, check=False)
    state.event("failed-vm-run-deletion-submitted", resourceGroup=names["vmResourceGroup"], reason=reason)


def _gate_markers(config: dict[str, Any], prefix: str) -> set[str]:
    names = runtime_names(config)
    normalized = prefix.rstrip("/") + "/"
    values = az_json("storage", "blob", "list", "--account-name", names["storageAccount"],
                     "--auth-mode", "login", "--container-name", names["gateContainer"],
                     "--prefix", normalized)
    return {str(item.get("name", "")).removeprefix(normalized) for item in values}


def _prepared_nodes(config: dict[str, Any]) -> set[str]:
    return _gate_markers(config, "prepared")


def prepare_vms(config: dict[str, Any], state: RunState) -> dict[str, Any]:
    nodes = node_names(config)
    ssh_dir = state.directory / "ssh"
    ssh_dir.mkdir(exist_ok=True)
    private = ssh_dir / "id_ed25519"
    if not private.exists():
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)])
    public = private.with_suffix(".pub").read_text(encoding="utf-8").strip()
    template_dir = state.directory / "arm-templates"
    template_dir.mkdir(exist_ok=True)
    provisioned = {name for name, value in state.data["nodes"].items()
                   if value.get("lastEvent") == "vm-provisioned"}
    pending = [node for node in nodes if node not in provisioned]
    batch_size = config["vmCreateBatchSize"]
    batches = [pending[offset:offset + batch_size] for offset in range(0, len(pending), batch_size)]
    deployment_concurrency = config["vmBatchDeploymentConcurrency"]
    try:
        for offset in range(0, len(batches), deployment_concurrency):
            wave = batches[offset:offset + deployment_concurrency]
            with concurrent.futures.ThreadPoolExecutor(max_workers=deployment_concurrency) as executor:
                futures = [executor.submit(_deploy_vm_batch, config, state, batch, template_dir, public)
                           for batch in wave]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
    except Exception as exc:
        _delete_failed_vm_run(config, state, f"ARM VM batch deployment failed: {type(exc).__name__}")
        raise
    deadline = time.monotonic() + int(config.get("vmPrepareTimeoutSeconds", 7200))
    prepared: set[str] = set()
    expected = set(nodes)
    last_progress = time.monotonic()
    last_count = 0
    while time.monotonic() < deadline:
        prepared = _prepared_nodes(config)
        print(f"VM preparation: {len(prepared)}/{len(expected)}", flush=True)
        if len(prepared) > last_count:
            last_count = len(prepared)
            last_progress = time.monotonic()
        if expected.issubset(prepared):
            break
        if time.monotonic() - last_progress >= config["vmPrepareNoProgressTimeoutSeconds"]:
            _delete_failed_vm_run(config, state, "VM preparation no-progress timeout")
            raise TimeoutError(
                f"VM preparation made no progress for {config['vmPrepareNoProgressTimeoutSeconds']} seconds; "
                f"prepared={len(prepared)}/{len(expected)}"
            )
        time.sleep(20)
    missing = sorted(expected - prepared)
    if missing:
        _delete_failed_vm_run(config, state, "VM preparation deadline exceeded")
        raise TimeoutError(f"only {len(prepared)}/{len(expected)} VMs reached the preparation barrier; missing={missing[:20]}")
    if config.get("bootstrapMode") == "local-config":
        names = runtime_names(config)
        run(["az", "storage", "blob", "delete", "--account-name", names["storageAccount"],
             "--auth-mode", "login", "--container-name", names["gateContainer"],
             "--name", "config/base.json"], timeout=60, check=False)
    # Joining must not have started before the gate.
    existing = kubectl_json("get", "nodes")
    unexpected = expected.intersection({item.get("metadata", {}).get("name") for item in existing.get("items", [])})
    if unexpected:
        raise RuntimeError(f"target Flex Nodes existed before the join gate: {sorted(unexpected)[:20]}")
    state.event("vm-fleet-prepared", count=len(prepared))
    return {"prepared": len(prepared)}


def _upload_gate(config: dict[str, Any]) -> None:
    names = runtime_names(config)
    with tempfile.NamedTemporaryFile() as handle:
        handle.write(b"start\n")
        handle.flush()
        az("storage", "blob", "upload", "--account-name", names["storageAccount"],
           "--auth-mode", "login", "--container-name", names["gateContainer"],
           "--name", "start", "--file", handle.name, "--overwrite")


def _machine_states(config: dict[str, Any], state: RunState) -> dict[str, str]:
    cluster = state.data["resources"]["clusterId"]
    url = (f"https://management.azure.com{cluster}/agentPools/{config['agentPoolName']}/machines"
           f"?api-version={config['bootstrapDataApiVersion']}")
    result: dict[str, str] = {}
    try:
        for _ in range(100):
            value = az_json("rest", "--method", "get", "--url", url, timeout=90)
            result.update({str(item.get("name")): str(item.get("properties", {}).get("provisioningState", ""))
                           for item in value.get("value", [])})
            next_link = value.get("nextLink")
            if not next_link:
                return result
            url = str(next_link)
    except CommandError:
        return result
    raise RuntimeError("ARM Machine listing exceeded 100 pages")


def _direct_machine_states(config: dict[str, Any], state: RunState, names: set[str]) -> dict[str, str]:
    cluster = state.data["resources"]["clusterId"]

    def fetch(name: str) -> tuple[str, str]:
        url = (f"https://management.azure.com{cluster}/agentPools/{config['agentPoolName']}/machines/{name}"
               f"?api-version={config['bootstrapDataApiVersion']}")
        try:
            value = az_json("rest", "--method", "get", "--url", url, timeout=60, attempts=2)
            return name, str(value.get("properties", {}).get("provisioningState", ""))
        except CommandError:
            return name, ""

    result: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, len(names) or 1)) as executor:
        for name, status in executor.map(fetch, sorted(names)):
            result[name] = status
    return result


def _node_states() -> dict[str, tuple[bool, datetime | None]]:
    value = kubectl_json("get", "nodes", timeout=60)
    result: dict[str, tuple[bool, datetime | None]] = {}
    for item in value.get("items", []):
        name = str(item.get("metadata", {}).get("name", ""))
        ready_condition = next((condition for condition in item.get("status", {}).get("conditions", [])
                                if condition.get("type") == "Ready"), None)
        transition = None
        if ready_condition and ready_condition.get("lastTransitionTime"):
            try:
                transition = datetime.fromisoformat(
                    str(ready_condition["lastTransitionTime"]).replace("Z", "+00:00")
                )
            except ValueError:
                transition = None
        result[name] = (bool(ready_condition and ready_condition.get("status") == "True"), transition)
    return result


def run_join(config: dict[str, Any], state: RunState) -> dict[str, Any]:
    allowed = set(node_names(config))
    machine_registration_required = config.get("bootstrapMode") == "rp"
    approved: set[str] = set()
    csr_cache: dict[str, tuple[str | None, bool, str]] = {}
    daemon_nodes: set[str] = set()
    ready_at: dict[str, float] = {}
    machine_success: set[str] = set()
    start_wall = datetime.now(timezone.utc)
    start = time.monotonic()
    state.data["joinStartedAt"] = start_wall.isoformat()
    state.save()
    _upload_gate(config)
    state.event("join-gate-opened", nodeCount=len(allowed))
    deadline = start + config["joinTimeoutSeconds"]
    last_machines = 0.0
    last_direct_machines = 0.0
    last_progress = start
    previous_progress = 0
    while time.monotonic() < deadline:
        now = time.monotonic()
        csrs = kubectl_json("get", "csr", timeout=60)
        for item in csrs.get("items", []):
            name = str(item.get("metadata", {}).get("name", ""))
            identity = csr_cache.get(name)
            if identity is None:
                identity = exact_identity(item, allowed)
                csr_cache[name] = identity
            node, daemon, reason = identity
            if not node:
                continue
            conditions = item.get("status", {}).get("conditions", [])
            if any(condition.get("type") == "Approved" for condition in conditions):
                if daemon:
                    daemon_nodes.add(node)
                continue
            if conditions or name in approved:
                continue
            result = run(["kubectl", "certificate", "approve", name], timeout=30, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"failed to approve exact CSR {name}")
            approved.add(name)
            if daemon:
                daemon_nodes.add(node)
            state.event("csr-approved", node=node, csr=name, daemon=daemon, reason=reason,
                        elapsedSeconds=round(time.monotonic() - start, 3))
        failed_bootstrap = _gate_markers(config, "failed")
        if failed_bootstrap:
            _delete_local_bootstrap_material(config)
            raise RuntimeError(
                f"bootstrap failed on {len(failed_bootstrap)} node(s): {sorted(failed_bootstrap)[:20]}"
            )
        nodes = _node_states()
        now = time.monotonic()
        for node in allowed:
            ready, transition = nodes.get(node, (False, None))
            if ready and node not in ready_at:
                # Kubernetes condition transition time remains accurate even when
                # a large CSR approval batch delays the next list/watch observation.
                elapsed_ready = ((transition - start_wall).total_seconds()
                                 if transition is not None else now - start)
                ready_at[node] = max(0.0, elapsed_ready)
                state.event("node-ready", node=node, elapsedSeconds=round(ready_at[node], 3))
        if machine_registration_required and now - last_machines >= 15:
            machine_success.update({name for name, status in _machine_states(config, state).items()
                                    if status == "Succeeded"})
            last_machines = now
        # The collection endpoint is known to fail transiently. Once every Node is Ready,
        # use bounded exact-name GETs only for unresolved Machines, at most every two minutes.
        if (machine_registration_required and allowed.issubset(ready_at)
                and machine_success != allowed and now - last_direct_machines >= 120):
            unresolved = allowed - machine_success
            machine_success.update({name for name, status in _direct_machine_states(config, state, unresolved).items()
                                    if status == "Succeeded"})
            last_direct_machines = now
        complete = allowed.intersection(ready_at).intersection(daemon_nodes)
        if machine_registration_required:
            complete.intersection_update(machine_success)
        progress = len(ready_at) + len(machine_success) + len(daemon_nodes) + len(approved)
        if progress > previous_progress:
            previous_progress = progress
            last_progress = now
        elif now - last_progress >= config["joinNoProgressTimeoutSeconds"]:
            _delete_local_bootstrap_material(config)
            raise TimeoutError(
                f"join made no progress for {config['joinNoProgressTimeoutSeconds']} seconds; "
                f"ready={len(ready_at)} machines={len(machine_success)} "
                f"daemonCredentials={len(daemon_nodes)} approvedCSRs={len(approved)}"
            )
        elapsed = now - start
        machine_progress = f"{len(machine_success)}/{len(allowed)}" if machine_registration_required else "skipped"
        print(f"join elapsed={elapsed:.0f}s ready={len(ready_at)}/{len(allowed)} "
              f"machines={machine_progress} daemonCredentials={len(daemon_nodes)}/{len(allowed)} "
              f"complete={len(complete)}/{len(allowed)}", flush=True)
        if complete == allowed:
            break
        time.sleep(config["pollIntervalSeconds"])
    elapsed = time.monotonic() - start
    complete = allowed.intersection(ready_at).intersection(daemon_nodes)
    if machine_registration_required:
        complete.intersection_update(machine_success)
    missing = sorted(allowed - complete)
    result = build_join_result(config, state, ready_at, elapsed, approved, missing)
    state.data["joinResult"] = result
    state.save()
    _delete_local_bootstrap_material(config)
    if missing:
        raise RuntimeError(f"100% readiness was not reached: {len(complete)}/{len(allowed)} complete; missing={missing[:20]}")
    return result


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile / 100 * len(ordered)) - 1)
    return round(ordered[index], 3)


def build_join_result(config: dict[str, Any], state: RunState, ready_at: dict[str, float], elapsed: float,
                      approved: set[str], missing: list[str]) -> dict[str, Any]:
    values = list(ready_at.values())
    duration = max(values) if values and not missing else elapsed
    return {
        "scenario": "aks-flex-node-scale-join",
        "target_node_count": config["nodeCount"],
        "ready_node_count": len(ready_at),
        "success": not missing and len(ready_at) == config["nodeCount"],
        "join_timeout_seconds": config["joinTimeoutSeconds"],
        "join_duration_seconds": round(duration, 3),
        "first_node_ready_seconds": round(min(values), 3) if values else None,
        "p50_node_ready_seconds": _percentile(values, 50),
        "p90_node_ready_seconds": _percentile(values, 90),
        "p95_node_ready_seconds": _percentile(values, 95),
        "p99_node_ready_seconds": _percentile(values, 99),
        "last_node_ready_seconds": round(max(values), 3) if values else None,
        "average_join_rate_per_minute": round(len(ready_at) / max(duration / 60, 1 / 60), 3),
        "csr_approved_count": len(approved),
        "missing_node_count": len(missing),
        "missing_nodes": missing,
        "bootstrap_mode": config.get("bootstrapMode"),
        "arm_machine_registration_required": config.get("bootstrapMode") == "rp",
        "versions": state.data["versions"],
        "host_validation": "placeholder-disabled" if not config.get("hostValidation") else "not-implemented",
    }


def validate_fleet(config: dict[str, Any], state: RunState) -> dict[str, Any]:
    expected = set(node_names(config))
    nodes = kubectl_json("get", "nodes")
    facts = {}
    for item in nodes.get("items", []):
        name = item.get("metadata", {}).get("name")
        if name not in expected:
            continue
        ready = any(condition.get("type") == "Ready" and condition.get("status") == "True"
                    for condition in item.get("status", {}).get("conditions", []))
        facts[name] = {"ready": ready, "site": item.get("metadata", {}).get("labels", {}).get("unbounded-cloud.io/site"),
                       "podCIDR": item.get("spec", {}).get("podCIDR")}
    invalid = [name for name in expected if name not in facts or not facts[name]["ready"]
               or facts[name]["site"] != "flex-site" or not facts[name]["podCIDR"]]
    machine_registration_required = config.get("bootstrapMode") == "rp"
    machines: dict[str, str] = {}
    bad_machines: list[str] = []
    if machine_registration_required:
        machines = _machine_states(config, state)
        unresolved_machines = {name for name in expected if machines.get(name) != "Succeeded"}
        if unresolved_machines:
            machines.update(_direct_machine_states(config, state, unresolved_machines))
        bad_machines = [name for name in expected if machines.get(name) != "Succeeded"]
    workload_started = time.monotonic()
    workload_deadline = workload_started + config["workloadValidationTimeoutSeconds"]
    net_nodes: set[str] = set()
    proxies: set[str] = set()
    while True:
        workloads = kubectl_json("-n", "unbounded-system", "get", "pods", timeout=120)
        net_nodes = set()
        proxies = set()
        for pod in workloads.get("items", []):
            if pod.get("status", {}).get("phase") != "Running":
                continue
            pod_name = str(pod.get("metadata", {}).get("name", ""))
            node_name = str(pod.get("spec", {}).get("nodeName", ""))
            if node_name not in expected:
                continue
            if "unbounded-net-node" in pod_name:
                net_nodes.add(node_name)
            if "kube-proxy" in pod_name:
                proxies.add(node_name)
        if net_nodes == expected and proxies == expected:
            break
        if time.monotonic() >= workload_deadline:
            break
        print(f"workload validation: net={len(net_nodes)}/{len(expected)} "
              f"kubeProxy={len(proxies)}/{len(expected)}", flush=True)
        time.sleep(10)
    workload_convergence_seconds = round(time.monotonic() - workload_started, 3)
    missing_net_nodes = sorted(expected - net_nodes)
    missing_proxies = sorted(expected - proxies)
    for resource in ("gatewaypools", "sitegatewaypoolassignments"): 
        if kubectl_json("get", resource).get("items"):
            raise RuntimeError(f"unexpected {resource} detected")
    result = {"nodesValidated": len(expected) - len(invalid),
              "machineRegistrationRequired": machine_registration_required,
              "machinesValidated": len(expected) - len(bad_machines) if machine_registration_required else 0,
              "unboundedNetNodesValidated": len(net_nodes), "managedKubeProxiesValidated": len(proxies),
              "workloadConvergenceSeconds": workload_convergence_seconds,
              "invalidNodes": invalid, "invalidMachines": bad_machines,
              "missingUnboundedNetNodes": missing_net_nodes, "missingManagedKubeProxies": missing_proxies,
              "hostValidation": {"enabled": False, "status": "deferred",
                                 "reason": "Host and nspawn validation is deferred for the initial scale benchmark."}}
    state.data["validation"] = result
    state.save()
    if invalid or bad_machines or missing_net_nodes or missing_proxies:
        raise RuntimeError(
            f"fleet validation failed: invalidNodes={len(invalid)} invalidMachines={len(bad_machines)} "
            f"missingNetNodes={len(missing_net_nodes)} missingKubeProxies={len(missing_proxies)}"
        )
    return result


def write_result(config: dict[str, Any], state: RunState, output: str | Path) -> dict[str, Any]:
    join_result = state.data.get("joinResult", {})
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": runtime_names(config)["runId"],
        "run_url": os.environ.get("BUILD_BUILDURI", "local"),
        "pipeline": os.environ.get("BUILD_DEFINITIONNAME", "local-aks-flex-scale"),
        "result": {
            **join_result,
            "phases": state.data.get("phases", {}),
        },
    }
    Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _resource_group_state(subscription: str, group: str) -> str | None:
    result = run(["az", "group", "show", "--subscription", subscription, "--name", group,
                  "--output", "json"], timeout=60, check=False)
    if result.returncode != 0:
        diagnostic = (result.stdout + result.stderr).decode("utf-8", "replace")
        if "ResourceGroupNotFound" in diagnostic or "could not be found" in diagnostic:
            return None
        raise CommandError(["az", "group", "show"], result.returncode, diagnostic)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"could not parse state for resource group {group}") from exc
    return str(value.get("properties", {}).get("provisioningState", "Unknown"))


def cleanup(config: dict[str, Any], state: RunState) -> None:
    names = runtime_names(config)
    groups = [names["vmResourceGroup"], names["aksResourceGroup"]]
    submitted: list[str] = []
    for group in groups:
        if _resource_group_state(config["subscriptionId"], group) is None:
            continue
        result = run(["az", "group", "delete", "--subscription", config["subscriptionId"], "--name", group,
                      "--yes", "--no-wait"], timeout=120, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"failed to submit deletion for resource group {group}")
        submitted.append(group)
    state.event("cleanup-submitted", resourceGroups=submitted)

    deadline = time.monotonic() + config["cleanupTimeoutSeconds"]
    remaining = set(submitted)
    while remaining and time.monotonic() < deadline:
        states: dict[str, str] = {}
        for group in list(remaining):
            group_state = _resource_group_state(config["subscriptionId"], group)
            if group_state is None:
                remaining.remove(group)
            else:
                states[group] = group_state
        if remaining:
            print(f"cleanup pending: {states}", flush=True)
            time.sleep(30)
    if remaining:
        raise TimeoutError(f"resource groups were not deleted before cleanup deadline: {sorted(remaining)}")
    state.event("cleanup-completed", resourceGroups=submitted)
