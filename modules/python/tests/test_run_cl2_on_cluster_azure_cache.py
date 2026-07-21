"""Tests for run-cl2-on-cluster.sh's per-worker Azure CLI cache isolation.

clustermesh-scale fans out up to N copies of this script concurrently
(scale.py execute_parallel). For provider=aks each worker must get its OWN
copy of the host's ~/.azure Azure CLI cache (never mutate the host cache),
must export CL2_AZURE_CONFIG_DIR pointing at it, must clean it up on exit,
must fail clearly if the host cache is missing, and must not disturb the
existing background-daemon (prometheus-cr-patcher / snapshot-daemon) EXIT
trap.

To keep the per-worker footprint bounded at n=100 concurrent workers (the
n100 disk-amplification blocker), the private copy MUST contain only
top-level REGULAR files from the host cache -- never directories (e.g. the
large cliextensions/, azuredevops/, logs/, commands/, telemetry/
subdirectories a real ~/.azure carries) and never symlinks (so a symlink
under ~/.azure can't be used to pull an arbitrary file into the private
copy). It must also fail closed if $HOME/.azure exists but contributes zero
top-level regular files.

Uses a fake `kubectl` (always exits 0, no output needed by any code path
exercised here) and a fake CL2 entry point standing in for
`scale.py execute` — it writes an empty-failure junit.xml immediately,
records the CL2_AZURE_CONFIG_DIR value it observed, and snapshots the
worker-private Azure cache dir's top-level entries (name/kind/size only —
never file contents) before this script's EXIT trap removes it — so these
tests run without docker/kubernetes/az.
"""

import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    REPO_ROOT
    / "steps"
    / "engine"
    / "clusterloader2"
    / "clustermesh-scale"
    / "run-cl2-on-cluster.sh"
)

FAKE_KUBECTL = "#!/bin/bash\nexit 0\n"

# Stands in for modules/python/clusterloader2/clustermesh-scale/scale.py's
# `execute` subcommand. Records the CL2_AZURE_CONFIG_DIR it observed and
# writes a zero-failure junit.xml so run-cl2-on-cluster.sh's pass/fail gate
# treats the run as a success without needing real CL2/docker/kubectl.
FAKE_CL2_EXECUTE = """#!/usr/bin/env python3
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument("mode")
parser.add_argument("--cl2-image")
parser.add_argument("--cl2-config-dir")
parser.add_argument("--cl2-report-dir", required=True)
parser.add_argument("--cl2-config-file")
parser.add_argument("--kubeconfig")
parser.add_argument("--provider")
parser.add_argument("--mock-mode")
parser.add_argument("--tear-down-prometheus", action="store_true")
args, _unused = parser.parse_known_args()

azure_dir = os.environ.get("CL2_AZURE_CONFIG_DIR", "")
with open(
    os.path.join(args.cl2_report_dir, "azure_config_dir_seen.txt"),
    "w", encoding="utf-8",
) as f:
    f.write(azure_dir)

# Snapshot the worker-private Azure cache dir's TOP-LEVEL entries (name,
# kind, size) *before* run-cl2-on-cluster.sh's EXIT trap removes it, so
# tests can assert on its contents afterwards. Never reads/logs file
# CONTENTS -- only names/kinds/sizes -- and only ever inspects the
# worker-PRIVATE copy, never the host's real ~/.azure.
listing_lines = []
if azure_dir and os.path.isdir(azure_dir):
    for entry in sorted(os.scandir(azure_dir), key=lambda e: e.name):
        if entry.is_symlink():
            kind = "symlink"
            size = 0
        elif entry.is_dir():
            kind = "dir"
            size = 0
        else:
            kind = "file"
            size = entry.stat().st_size
        listing_lines.append(f"{kind}:{entry.name}:{size}")
with open(
    os.path.join(args.cl2_report_dir, "azure_private_listing.txt"),
    "w", encoding="utf-8",
) as f:
    f.write("\\n".join(listing_lines))

with open(
    os.path.join(args.cl2_report_dir, "junit.xml"), "w", encoding="utf-8",
) as f:
    f.write(
        '<testsuites><testsuite name="fake" tests="1" '
        'failures="0" errors="0"></testsuite></testsuites>'
    )
"""


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_host_env(tmp_path, with_azure_cache=True):
    """Set up a fake $HOME (with or without ~/.azure) + fake kubectl on
    PATH + TMPDIR pinned under tmp_path, and return the env dict plus the
    path to the fake host Azure cache dir."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    _write_executable(fake_bin / "kubectl", FAKE_KUBECTL)

    fake_home = tmp_path / "home"
    fake_azure = fake_home / ".azure"
    if with_azure_cache:
        fake_azure.mkdir(parents=True)
        (fake_azure / "msal_token_cache.json").write_text(
            '{"tokens": "fake-token-cache"}', encoding="utf-8"
        )
        (fake_azure / "azureProfile.json").write_text(
            '{"subscriptions": []}', encoding="utf-8"
        )
    else:
        fake_home.mkdir(parents=True)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["TMPDIR"] = str(tmp_path)
    env.pop("CL2_AZURE_CONFIG_DIR", None)
    return env, fake_azure


# Bytes per nested "large" file planted under a real-world-shaped ~/.azure
# subdirectory (cliextensions/, azuredevops/, logs/, commands/, telemetry/).
# Kept small enough for a fast test while still being orders of magnitude
# bigger than the root auth/profile files, so an amplification bug (nested
# content leaking into the private copy) is trivially detectable by size.
_NESTED_LARGE_FILE_BYTES = 256 * 1024


def _fake_host_env_realistic(tmp_path):
    """Build a fake $HOME/.azure shaped like a real-world Azure CLI cache:
    top-level auth/profile regular files PLUS the large nested subdirectories
    that dominate a real cache's on-disk footprint (cliextensions/,
    azuredevops/, logs/, commands/, telemetry/), PLUS top-level symlinks.
    Returns (env, fake_azure_dir, root_file_names, root_files_total_bytes,
    nested_total_bytes)."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    _write_executable(fake_bin / "kubectl", FAKE_KUBECTL)

    fake_home = tmp_path / "home"
    fake_azure = fake_home / ".azure"
    fake_azure.mkdir(parents=True)

    # Root-level files CL2/kubelogin actually need -- must all survive.
    root_files = {
        "azureProfile.json": '{"subscriptions": []}',
        "msal_token_cache.json": '{"tokens": "fake-token-cache"}',
        "msal_http_cache.bin": "binary-ish-cache-content",
        "clouds.config": "[AzureCloud]\nendpoint=https://management.azure.com",
        "config": "[core]\noutput = json",
    }
    for name, content in root_files.items():
        (fake_azure / name).write_text(content, encoding="utf-8")
    root_files_total_bytes = sum(
        (fake_azure / name).stat().st_size for name in root_files
    )

    # Large nested subdirectories that must NEVER be copied.
    nested_dirs = ["cliextensions", "azuredevops", "logs", "commands", "telemetry"]
    nested_total_bytes = 0
    for dname in nested_dirs:
        d = fake_azure / dname / "nested" / "deep"
        d.mkdir(parents=True)
        big_file = d / "big.bin"
        big_file.write_bytes(b"x" * _NESTED_LARGE_FILE_BYTES)
        nested_total_bytes += big_file.stat().st_size

    # Top-level symlink pointing OUTSIDE the cache root -- must never be
    # followed/copied, so it can't be used to smuggle an arbitrary host
    # file into a worker's private copy.
    outside_secret = tmp_path / "outside_secret.txt"
    outside_secret.write_text("not-part-of-the-azure-cache", encoding="utf-8")
    (fake_azure / "sneaky_link.json").symlink_to(outside_secret)

    # Top-level symlink pointing at a directory -- must also be excluded
    # (it is neither a plain regular file nor a real top-level directory).
    (fake_azure / "cliextensions_link").symlink_to(
        fake_azure / "cliextensions", target_is_directory=True
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["TMPDIR"] = str(tmp_path)
    env.pop("CL2_AZURE_CONFIG_DIR", None)
    return env, fake_azure, set(root_files), root_files_total_bytes, nested_total_bytes


def _read_private_listing(report_dir):
    """Parse the fake CL2 execute stub's azure_private_listing.txt (written
    while the worker-private Azure cache dir still existed, before this
    script's EXIT trap removed it) into {name: (kind, size)}."""
    text = (report_dir / "azure_private_listing.txt").read_text(encoding="utf-8")
    listing = {}
    for line in text.splitlines():
        if not line:
            continue
        kind, name, size = line.split(":", 2)
        listing[name] = (kind, int(size))
    return listing


def _run_worker(tmp_path, role, report_dir, env, provider="aks"):
    cl2_stub = tmp_path / f"fake_execute_{role}.py"
    _write_executable(cl2_stub, FAKE_CL2_EXECUTE)

    kubeconfig = tmp_path / f"{role}.kubeconfig"
    kubeconfig.write_text("apiVersion: v1\nkind: Config\n", encoding="utf-8")
    cl2_config_dir = tmp_path / f"{role}-cl2-config"
    cl2_config_dir.mkdir(exist_ok=True)

    args = [
        "bash", str(SCRIPT),
        role,
        str(kubeconfig),
        str(report_dir),
        "test-cl2-image",
        str(cl2_config_dir),
        "config.yaml",
        provider,
        str(cl2_stub),
        str(tmp_path),
    ]
    return subprocess.run(
        args, check=False, capture_output=True, text=True, env=env, timeout=60,
    )


def test_script_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"bash -n failed: stderr={result.stderr}"


def test_aks_worker_gets_private_copy_of_host_azure_cache(tmp_path):
    env, fake_azure = _fake_host_env(tmp_path)
    report_dir = tmp_path / "report"

    result = _run_worker(tmp_path, "mesh-1", report_dir, env, provider="aks")

    assert result.returncode == 0, result.stdout + result.stderr

    seen_path = (report_dir / "azure_config_dir_seen.txt").read_text(
        encoding="utf-8"
    ).strip()
    assert seen_path, "CL2_AZURE_CONFIG_DIR was not exported to the CL2 execute step"
    assert seen_path != str(fake_azure), (
        "worker used the host ~/.azure directly instead of a private copy"
    )

    # The private dir must not live under report_dir (not a test artifact).
    assert not seen_path.startswith(str(report_dir)), (
        "worker-private Azure cache was created under report_dir"
    )

    # Cleanup: the private dir must be gone once the script has exited.
    assert not os.path.exists(seen_path), (
        "worker-private Azure cache was not cleaned up on exit"
    )

    # Host cache must be untouched: still exactly the two original files
    # with their original content (copy, never mutate/move).
    host_files = sorted(p.name for p in fake_azure.iterdir())
    assert host_files == ["azureProfile.json", "msal_token_cache.json"]
    assert (fake_azure / "msal_token_cache.json").read_text(
        encoding="utf-8"
    ) == '{"tokens": "fake-token-cache"}'


def test_nested_directories_and_symlinks_excluded_root_files_copied(tmp_path):
    """Proves the n100 disk-amplification fix: only top-level REGULAR files
    are copied into the worker-private Azure CLI cache. The large nested
    subdirectories that dominate a real ~/.azure's footprint (cliextensions/,
    azuredevops/, logs/, commands/, telemetry/) and top-level symlinks
    (including one pointing OUTSIDE the cache root) must be entirely absent
    from the private copy, while every root auth/profile file that CL2 /
    kubelogin depend on must be present with its mode preserved."""
    env, fake_azure, root_file_names, root_files_total_bytes, nested_total_bytes = (
        _fake_host_env_realistic(tmp_path)
    )
    report_dir = tmp_path / "report"

    result = _run_worker(tmp_path, "mesh-1", report_dir, env, provider="aks")
    assert result.returncode == 0, result.stdout + result.stderr

    listing = _read_private_listing(report_dir)

    # Every root auth/profile file must have been copied through.
    for name in root_file_names:
        assert name in listing, f"required root file {name!r} missing from private cache"
        kind, _size = listing[name]
        assert kind == "file", f"{name!r} should be a plain file, got {kind!r}"

    # No nested subdirectory made it into the private cache -- not as a
    # directory, and (since we only ever list the private cache's TOP
    # level) their large nested content can't be present under any name.
    for dname in ["cliextensions", "azuredevops", "logs", "commands", "telemetry"]:
        assert dname not in listing, (
            f"large nested directory {dname!r} was copied into the "
            "worker-private Azure cache"
        )

    # Neither top-level symlink was copied (not as a symlink, not
    # resolved/dereferenced into a regular file under a different name).
    assert "sneaky_link.json" not in listing, (
        "a symlink pointing outside the cache root was copied"
    )
    assert "cliextensions_link" not in listing, (
        "a symlink pointing at a nested directory was copied"
    )

    # Conceptual amplification bound: the private copy's total top-level
    # size must equal (roughly) just the root files' bytes, and must be
    # MUCH smaller than the nested content that a naive recursive copy
    # would have pulled in. This is the crux of the n100 blocker fix -- the
    # per-worker footprint no longer scales with ~/.azure's nested content
    # (extensions/logs/telemetry/azuredevops), so it stays bounded
    # regardless of how many workers (N) run concurrently.
    private_total_bytes = sum(size for _kind, size in listing.values())
    assert private_total_bytes <= root_files_total_bytes + 64, (
        "worker-private Azure cache is larger than the root files alone -- "
        "nested content leaked in"
    )
    assert private_total_bytes < nested_total_bytes, (
        "worker-private Azure cache footprint was not bounded away from the "
        "large nested directories' content"
    )

    # Host cache must remain untouched (still has its nested dirs/symlinks).
    assert (fake_azure / "cliextensions").is_dir()
    assert (fake_azure / "sneaky_link.json").is_symlink()


def test_only_nested_content_present_fails_closed(tmp_path):
    """If $HOME/.azure exists but has no top-level REGULAR files (e.g. only
    subdirectories survived some prior partial state), the script must fail
    closed rather than hand CL2 an empty, useless private cache."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    _write_executable(fake_bin / "kubectl", FAKE_KUBECTL)

    fake_home = tmp_path / "home"
    fake_azure = fake_home / ".azure"
    (fake_azure / "cliextensions" / "nested").mkdir(parents=True)
    (fake_azure / "cliextensions" / "nested" / "ext.bin").write_bytes(b"x" * 4096)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["TMPDIR"] = str(tmp_path)
    env.pop("CL2_AZURE_CONFIG_DIR", None)

    report_dir = tmp_path / "report"
    result = _run_worker(tmp_path, "mesh-1", report_dir, env, provider="aks")

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "no top-level regular files" in combined
    # Must fail BEFORE ever invoking the CL2 execute step.
    assert not (report_dir / "junit.xml").exists()
    assert not (report_dir / "azure_config_dir_seen.txt").exists()


def test_missing_host_azure_cache_fails_clearly(tmp_path):
    env, _fake_azure = _fake_host_env(tmp_path, with_azure_cache=False)
    report_dir = tmp_path / "report"

    result = _run_worker(tmp_path, "mesh-1", report_dir, env, provider="aks")

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Azure CLI" in combined
    assert "az aks get-credentials" in combined
    # Must fail BEFORE ever invoking the CL2 execute step.
    assert not (report_dir / "junit.xml").exists()
    assert not (report_dir / "azure_config_dir_seen.txt").exists()


def _fake_cp_script(marker_dir):
    """Fake `cp` that records the destination path it was invoked with
    (so the test can assert it was cleaned up) and always fails, simulating
    a disk-full/permission/corruption failure while populating the
    worker-private Azure CLI cache copy."""
    return (
        "#!/bin/bash\n"
        "for arg in \"$@\"; do dest=\"$arg\"; done\n"
        f"echo \"$dest\" > {marker_dir}/dest.txt\n"
        "echo 'fake cp: simulated copy failure' >&2\n"
        "exit 1\n"
    )


def test_mktemp_failure_fails_closed_before_any_copy(tmp_path):
    """If `mktemp -d` fails, the script must fail immediately -- never fall
    through to the `cp` line with an empty/garbage azure_private_dir (which
    would turn the copy destination into bare "/"). The script runs under
    `set -uo pipefail` (no `-e`), so this must be an EXPLICIT check, not
    something the shell catches automatically."""
    env, fake_azure = _fake_host_env(tmp_path)
    report_dir = tmp_path / "report"

    fake_bin = Path(env["PATH"].split(os.pathsep)[0])
    _write_executable(
        fake_bin / "mktemp",
        "#!/bin/bash\necho 'fake mktemp: simulated failure' >&2\nexit 1\n",
    )

    result = _run_worker(tmp_path, "mesh-1", report_dir, env, provider="aks")

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "mktemp" in combined
    # Must fail BEFORE ever invoking cp or the CL2 execute step.
    assert not (report_dir / "junit.xml").exists()
    assert not (report_dir / "azure_config_dir_seen.txt").exists()
    # The host cache must be untouched.
    host_files = sorted(p.name for p in fake_azure.iterdir())
    assert host_files == ["azureProfile.json", "msal_token_cache.json"]


def test_cp_failure_cleans_up_temp_dir_and_fails_closed(tmp_path):
    """If populating the worker-private Azure CLI cache copy fails, the
    script must explicitly clean up the (partially populated, unusable)
    temp dir and exit non-zero -- never proceed to export
    CL2_AZURE_CONFIG_DIR or invoke the CL2 execute step against a broken
    cache."""
    env, _fake_azure = _fake_host_env(tmp_path)
    report_dir = tmp_path / "report"

    tmp_marker_dir = tmp_path / "cp-marker"
    tmp_marker_dir.mkdir()
    fake_bin = Path(env["PATH"].split(os.pathsep)[0])
    _write_executable(
        fake_bin / "cp",
        _fake_cp_script(tmp_marker_dir),
    )

    result = _run_worker(tmp_path, "mesh-1", report_dir, env, provider="aks")

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "failed to populate worker-private Azure CLI cache" in combined
    # Must fail BEFORE ever invoking the CL2 execute step.
    assert not (report_dir / "junit.xml").exists()
    assert not (report_dir / "azure_config_dir_seen.txt").exists()

    # The fake cp recorded the destination dir it was asked to populate;
    # confirm the script removed it (explicit cleanup) rather than leaving
    # a broken/partial private cache dir behind.
    recorded_dest = (tmp_marker_dir / "dest.txt").read_text(encoding="utf-8").strip()
    assert recorded_dest, "fake cp did not record a destination path"
    assert not os.path.exists(recorded_dest), (
        f"worker-private Azure cache dir {recorded_dest!r} was not cleaned "
        "up after a cp failure"
    )


def test_non_aks_provider_does_not_set_cl2_azure_config_dir(tmp_path):
    env, _fake_azure = _fake_host_env(tmp_path)
    report_dir = tmp_path / "report"

    result = _run_worker(tmp_path, "mesh-1", report_dir, env, provider="aws")

    assert result.returncode == 0, result.stdout + result.stderr
    seen_path = (report_dir / "azure_config_dir_seen.txt").read_text(
        encoding="utf-8"
    ).strip()
    assert seen_path == "", (
        "CL2_AZURE_CONFIG_DIR must stay unset for non-aks providers"
    )


def test_concurrent_workers_get_distinct_private_dirs(tmp_path):
    env, _fake_azure = _fake_host_env(tmp_path)
    report_dir_a = tmp_path / "report-a"
    report_dir_b = tmp_path / "report-b"

    cl2_stub_a = tmp_path / "fake_execute_a.py"
    cl2_stub_b = tmp_path / "fake_execute_b.py"
    _write_executable(cl2_stub_a, FAKE_CL2_EXECUTE)
    _write_executable(cl2_stub_b, FAKE_CL2_EXECUTE)

    def _args(role, report_dir, cl2_stub):
        kubeconfig = tmp_path / f"{role}.kubeconfig"
        kubeconfig.write_text("apiVersion: v1\nkind: Config\n", encoding="utf-8")
        cl2_config_dir = tmp_path / f"{role}-cl2-config"
        cl2_config_dir.mkdir(exist_ok=True)
        return [
            "bash", str(SCRIPT),
            role, str(kubeconfig), str(report_dir), "test-cl2-image",
            str(cl2_config_dir), "config.yaml", "aks", str(cl2_stub),
            str(tmp_path),
        ]

    with subprocess.Popen(
        _args("mesh-a", report_dir_a, cl2_stub_a),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    ) as proc_a, subprocess.Popen(
        _args("mesh-b", report_dir_b, cl2_stub_b),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    ) as proc_b:
        out_a, _ = proc_a.communicate(timeout=60)
        out_b, _ = proc_b.communicate(timeout=60)

    assert proc_a.returncode == 0, out_a
    assert proc_b.returncode == 0, out_b

    seen_a = (report_dir_a / "azure_config_dir_seen.txt").read_text(
        encoding="utf-8"
    ).strip()
    seen_b = (report_dir_b / "azure_config_dir_seen.txt").read_text(
        encoding="utf-8"
    ).strip()
    assert seen_a and seen_b
    assert seen_a != seen_b, "concurrent workers must not share a private Azure cache dir"
    assert not os.path.exists(seen_a)
    assert not os.path.exists(seen_b)


def test_trap_still_kills_background_daemon_pids(tmp_path):
    """The EXIT trap must still terminate prometheus-cr-patcher and the
    snapshot-daemon background PIDs, even after being extended to also
    clean up the worker-private Azure cache dir."""
    env, _fake_azure = _fake_host_env(tmp_path)
    report_dir = tmp_path / "report"

    result = _run_worker(tmp_path, "mesh-1", report_dir, env, provider="aks")
    assert result.returncode == 0, result.stdout + result.stderr

    combined = result.stdout + result.stderr
    prom_pid = None
    snapshot_pid = None
    for line in combined.splitlines():
        if "spawned prometheus-cr-patcher" in line and "PID=" in line:
            prom_pid = int(line.split("PID=")[1].split(",")[0].split(")")[0])
        if "spawned snapshot-daemon" in line and "PID=" in line:
            snapshot_pid = int(line.split("PID=")[1].split(",")[0].split(")")[0])

    assert prom_pid is not None, combined
    assert snapshot_pid is not None, combined

    # Give the OS a brief moment to reap the killed processes, then confirm
    # neither PID is alive any more (signal 0 => existence check only).
    for _ in range(20):
        prom_alive = _pid_alive(prom_pid)
        snapshot_alive = _pid_alive(snapshot_pid)
        if not prom_alive and not snapshot_alive:
            break
        time.sleep(0.1)

    assert not _pid_alive(prom_pid), (
        f"prometheus-cr-patcher PID {prom_pid} was not terminated by the EXIT trap"
    )
    assert not _pid_alive(snapshot_pid), (
        f"snapshot-daemon PID {snapshot_pid} was not terminated by the EXIT trap"
    )


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but owned elsewhere -- treat as alive.
        return True
    return True
