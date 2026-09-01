# Elastic SAN Static Scale Pipeline

This Azure DevOps pipeline grows static Azure Elastic SAN volumes for an existing AKS cluster,
records provisioning time and success rate, and optionally creates static PV/PVC/Pod attachments
in a separate stage.

## Identity and resume model

- `cluster_id` accepts only the full AKS ARM resource ID. The subscription ID, resource group,
  and cluster name are parsed from that single value.
- The pipeline resolves that identifier with Bash (`az aks` + `jq`) and passes the resulting
  `cluster.json` contract to the Python provision and attach workers.
- Managed SAN names use the fixed `tel-esan` prefix and are derived from the cluster UID.
- Azure tags persist ownership, SAN index, and geometry across pipeline runs.
- Volume-group network ACLs use all subnet IDs discovered from AKS agent-pool metadata.
- Existing `san.csi.azure.com` PV handles and volumes in tagged SANs are unioned and deduplicated.
- Raising `target_total_volumes` adds only the missing objects. A full SAN is never modified;
  another SAN is created automatically.

For example, if the cluster already has 20,000 ESAN PVs and the target is 40,000, the default
`200 groups x 100 volumes` geometry plans one new 20,000-volume SAN.

For the current scale cluster, queue the generated pipeline first with:

```text
cluster_id: /subscriptions/b8ceb4e5-f05b-4562-a9f5-14acb1f24219/resourceGroups/acstor-160k-sea/providers/Microsoft.ContainerService/managedClusters/aksacstor160ksea
run_provision: true
run_repair: false
run_attach: false
target_total_volumes: 40000
volume_groups_per_san: 200
volumes_per_group: 100
volume_size_gib: 1
base_size_tib: 3
extended_size_tib: 17
availability_zone: 2
max_volume_writes_per_hour: 3000
```

The verified local read-only check for these values planned one new SAN,
`tel-esan-fdad3da6-00`, with 20,000 new volume objects. For the long-term 120K target, the
same layout plans five new 20K SANs from the current 20K baseline. The pipeline checks that the
result fits the known 10-SAN regional quota before making writes.

## Select stages when queuing

Azure DevOps displays these boolean parameters as checkboxes:

| Parameter | Behavior |
|---|---|
| `run_provision` | Create missing SANs, VGs, and static volumes |
| `run_repair` | Delete Failed managed volumes and recreate the same names, up to four rounds |
| `run_attach` | Create PV/PVC/Pod resources only for successful volumes not currently attached |

The selected stages run in `provision -> repair -> attach` order. A stage can run by itself;
skipped dependencies do not block it. Recommended sequences are:

- First run: select only `run_provision` to preserve the raw provisioning result.
- Repair run: select only `run_repair`, or select Provision + Repair in one run.
- Attach run: select only `run_attach`; only successful managed volumes without an attached
  `VolumeAttachment` in this AKS cluster are selected.
- End-to-end run: select all three. Attach starts only if Repair succeeds.

If no checkbox is selected, only cluster validation runs.

Provision, Repair, and Attach results are published as separate Azure DevOps pipeline artifacts.
Provision records elapsed time and success rates for the run, each SAN, and each VG. Attach
records selected unattached volumes, Ready Pods, and successful VolumeAttachments.

## Important semantics

- `target_total_volumes` is the desired count of unique volume **objects**, including existing
  ESAN PV handles and pipeline-managed volumes not attached yet.
- `volume_groups_per_san * volumes_per_group` must not exceed the enforced 20,000-volume SAN cap.
- The default 3 TiB base + 17 TiB extended capacity holds 20,000 x 1 GiB volumes.
- New SANs default to availability zone `2`; set `availability_zone` to an empty value when
  zonal placement is not required or supported in the target region.
- `max_volume_writes_per_hour` is a per-stage client-side rolling-window budget for SAN, VG,
  Volume PUT, and Repair DELETE operations. The 3,610-second window defaults to 3,000 writes,
  leaving 600 writes of headroom below the subscription's 3,600 writes/hour limit.
- The limiter is local to one Provision or Repair job. Separate pipeline runs and stages do not
  share counters, so do not overlap runs for the same subscription. Prefer a separate Repair run
  after Provision when the preceding hour used the full write budget.
- Raw `Succeeded`, `Failed`, and missing/nonterminal counts are preserved in the provision artifact.
  Attach consumes only `Succeeded` volumes with a usable iSCSI target and excludes handles with
  `VolumeAttachment.status.attached=true` in the target AKS cluster. Existing incomplete
  PV/PVC/Pod resources remain eligible for reconciliation.
- Attachment nodes must have room for `pods_per_node` additional Pods plus 10 reserved Pod
  slots; candidates are ordered by their current scheduled-Pod count so existing
  high-density nodes are avoided.
- Failed volume repair is a separate optional stage, so the raw provisioning success rate remains
  unchanged. Repair writes its own before/after summary and fails if volumes remain unrepaired
  after four rounds.
- Do not queue overlapping runs for the same AKS cluster. Provision, Repair, and Attach are
  ordered within one run, but separate Azure DevOps runs do not share a cluster-level lock.

## Generate YAML

```bash
kcl run kcl/ccp_team/elastic_san_static_scale/pipeline.k -S output \
  -o kcl/ccp_team/elastic_san_static_scale/pipeline.yaml
```

Run unit tests with:

```bash
python3 -m unittest \
  kcl/ccp_team/elastic_san_static_scale/test_elastic_san_static_scale.py
```