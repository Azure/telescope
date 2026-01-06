# Pipeline Schedules

Complete overview of all pipeline schedules in the Telescope project.

## API Server Benchmark

### apiserver-benchmark-configmaps100.yml
- **Schedule:** `0 3 * * *`
- **Display Name:** 3:00 AM Daily

### apiserver-benchmark-virtualnodes10-pods100.yml
- **Schedule:** `0 */1 * * *`
- **Display Name:** Every Hour

### apiserver-benchmark-virtualnodes100-pods3k.yml
- **Schedule:** `0 0 * * *`
- **Display Name:** 12:00 AM Daily

### apiserver-benchmark-virtualnodes100-pods10k.yml
- **Schedule:** `0 12 * * *`
- **Display Name:** 12:00 PM Daily

---

## Autoscale Benchmark

### cluster-autoscaler-benchmark.yml
- **Schedule 1:** `0 1 * * *` - 1:00 AM Daily
- **Schedule 2:** `0 1 * * 2,6` - 1:00 AM on Tuesday and Saturday
- **Schedule 3:** `0 12 * * *` - Every day at 12:00 PM
- **Schedule 4:** `0 12 * * 0` - Every day at 12:00 PM on Sunday
- **Schedule 5:** `0 0 * * 5` - 12:00 AM on Friday
- **Schedule 6:** `0 6 * * 4` - 6:00 AM on Thursday

### cluster-autoscaler-benchmark-nodes200-ab-testing.yml
- **Schedule:** `0 8,20 * * *`
- **Display Name:** Every day at 8:00 AM and 8:00 PM

### node-auto-provisioning-benchmark.yml
- **Schedule 1:** `0 3 * * *` - 3:00 AM Daily
- **Schedule 2:** `0 0 * * 2,6` - 12:00 AM on Tuesday and Saturday
- **Schedule 3:** `0 6 * * *` - Every day at 6:00 AM
- **Schedule 4:** `0 0 * * *` - Every day at 12:00 AM
- **Schedule 5:** `0 6 * * 1` - 6:00 AM on Monday
- **Schedule 6:** `0 0 1,15 * *` - Every 15 days at 12:00 AM

### node-auto-provisioning-benchmark-complex.yml
- **Schedule:** `0 21 * * *`
- **Display Name:** Every day at 9:00 PM

---

## Automatic Benchmark

### cluster-automatic-single-cluster.yml
- **Schedule:** `0 15/6 * * *`
- **Display Name:** Every 6 hours starting at 3:00 PM

---

## CNI Benchmark

### cni-ab-testing.yml
- **Schedule:** `0 1-23/4 * * *`
- **Display Name:** Every 4 Hour (1AM start)

---

## CRI Benchmark

### azurelinux-resource-consume.yml
- **Schedule:** `0 */4 * * *`
- **Display Name:** Every 4 Hour

### cri-kbench-cp-bottlerocket.yml
- **Status:** No schedule (manual trigger only)

### cri-resource-consume.yml
- **Schedule:** `0 2-23/4 * * *`
- **Display Name:** Every 4 Hour

### flatcar-resource-consume.yml
- **Schedule:** `30 3-23/4 * * *`
- **Display Name:** Every 4 Hour (at 30 minutes past)

### konnectivity-resource-consume.yml
- **Status:** Commented out
- **Schedule (if enabled):** `0 2-23/4 * * *` - Every 4 Hours

### windows-resource-consume.yml
- **Status:** No schedule (manual trigger only)

---

## CSI Benchmark

### csi-attach-detach-300.yml
- **Schedule 1:** `0 16 * * *` - 4:00 PM Every Day
- **Schedule 2:** `0 16 * * 4` - 4:00 PM on Thursdays

### csi-attach-detach-1000.yml
- **Schedule 1:** `0 20 * * *` - 8:00 PM Every Day
- **Schedule 2:** `0 20 * * 3` - 8:00 PM on Wednesdays

---

## GPU Benchmark

### k8s-gpu-cluster-crud.yml
- **Schedule 1:** `0 */6 * * *` - Every 6 hours
- **Schedule 2:** `30 */6 * * *` - At 30 minutes past every 6th hour
- **Schedule 3:** `0 13-23 20 * *` - 20th of every month for every 1 hour (1:00 PM - 11:00 PM)
- **Schedule 4:** `0 0-12 21 * *` - 21st of every month for every 1 hour (12:00 AM - 12:00 PM)

### k8s-gpu-scheduling.yml
- **Schedule 1:** `0 8 * * *` - 8:00 AM daily (small scale)
- **Schedule 2:** `0 20 * * 1,3` - 8:00 PM on Mondays and Wednesdays (medium scale)
- **Schedule 3:** `0 20 * * 4` - 8:00 PM on Thursdays (high scale)

### k8s-ray-scheduling.yml
- **Schedule 1:** `0 0 * * *` - 12:00 AM daily (small scale)
- **Schedule 2:** `0 12 * * 1,3` - 12:00 PM on Mondays and Wednesdays (medium scale)
- **Schedule 3:** `0 12 * * 4` - 12:00 PM on Thursdays (high scale)

---

## Large Cluster Benchmark

### cluster-churn.yml
- **Schedule 1:** `0 */12 * * *` - 12:00 AM & PM Daily
- **Schedule 2:** `0 12 * * 1` - 12:00 PM on Mondays

### service-churn.yml
- **Schedule 1:** `0 6,18 * * *` - 6:00 AM & PM Daily
- **Schedule 2:** `0 6 * * 2` - 6:00 AM on Tuesdays

---

## Network Benchmark

### pod-to-pod-diff-node-same-zone-same-cluster.yml
- **Schedule 1:** `0 11 * * *` - 11:00 AM Daily
- **Schedule 2:** `0 23 * * *` - 11:00 PM Daily

---

## Scheduler Benchmark

### job-scheduling.yml
- **Schedule 1:** `0 4 * * *` - 4:00 AM daily (small scale)
- **Schedule 2:** `0 16 * * 1,3` - 4:00 PM on Mondays and Wednesdays (medium scale)
- **Schedule 3:** `0 16 * * 4` - 4:00 PM on Thursdays (high scale)

### pod-churn-50k-sched.yml
- **Schedule:** `30 1/12 * * *`
- **Display Name:** 1:30 AM and PM every day

---

## Secure TLS Bootstrap Benchmark

### cri-resource-consume.yml
- **Schedule 1:** `0 9,21 * * *` - 9:00 AM & 9:00 PM Daily
- **Schedule 2:** `0 13,19 * * *` - 1:00 PM & 7:00 PM Daily

### cluster-autoscaler.yml
- **Schedule 1:** `0 7 * * *` - 7:00 AM Daily
- **Schedule 2:** `0 11 * * *` - 11:00 AM Daily

---

## Storage Benchmark

### k8s-nvme-disk-fio.yml
- **Schedule:** `15 3 * * *`
- **Display Name:** Daily at 3:15 AM

### k8s-os-disk-fio.yml
- **Schedule 1:** `0 10 */2 * *` - Every Even Day at 10:00 AM
- **Schedule 2:** `0 10 * * 1` - Every Week on Monday at 10:00 AM

---

## System Pipelines

### aws-capacity-reservation.yml
- **Status:** No schedule (manual trigger only)

### new-pipeline-test.yml
- **Status:** Template file (no schedule)

### pipeline-validator.yml
- **Schedule:** `0 */6 * * *`
- **Display Name:** Every 6 hours

---

## Cron Expression Reference

| Field | Allowed Values | Special Characters |
|-------|---------------|--------------------|
| Minute | 0-59 | `,` `-` `*` `/` |
| Hour | 0-23 | `,` `-` `*` `/` |
| Day of Month | 1-31 | `,` `-` `*` `/` `?` `L` `W` |
| Month | 1-12 | `,` `-` `*` `/` |
| Day of Week | 0-6 (0=Sunday) | `,` `-` `*` `/` `?` `L` `#` |

### Common Examples
- `0 4 * * *` - 4:00 AM every day
- `0 */6 * * *` - Every 6 hours
- `0 9,21 * * *` - 9:00 AM and 9:00 PM every day
- `0 0 * * 1` - 12:00 AM every Monday
- `30 1/12 * * *` - 1:30 AM and 1:30 PM every day
