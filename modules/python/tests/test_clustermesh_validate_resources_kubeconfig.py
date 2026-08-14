"""Tests for the reusable AKS kubeconfig-fetch helper embedded in
steps/topology/clustermesh-scale/validate-resources.yml (build 74260 fix).

Build 74260 evidence: ClusterMesh/KVStoreMesh was already Connected and the
initial sequential kubeconfig prefetch (in the "Wait for
clustermesh-apiserver..." step) had already succeeded for every cluster, but
the per-cluster "Validate Cilium + ClusterMesh on every cluster" step then
unconditionally re-ran `az aks get-credentials` for mesh-1 anyway. Azure
returned ServerTimeout after ~140s on that single, un-retried, redundant call
and failed the whole job with Bash exit 1 (RG cleanup still ran and
succeeded).

The fix adds a `fetch_kubeconfig()` / `kubeconfig_is_valid()` /
`ensure_kubeconfig()` helper library, written once (as a heredoc) by the
"Enumerate clustermesh clusters" step to $HOME/.kube/lib/fetch-kubeconfig.sh
and `source`d by every later `script:` step that needs it — each
Azure Pipelines `script:` step is its own bash process, so steps cannot share
shell functions directly, only files persisted under $HOME across the job.

These tests extract the exact heredoc body embedded in validate-resources.yml
(rather than duplicating it), write it to a real file, and exercise it with a
fake `az` on PATH — consistent with how test_clustermesh_scale.py::
TestNodeChurnerScript and test_clustermesh_mock_provision_script.py fake `az`/
`kubectl` for the vendored shell scripts in this repo.
"""

import os
import re
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
YAML_PATH = (
    REPO_ROOT
    / "steps"
    / "topology"
    / "clustermesh-scale"
    / "validate-resources.yml"
)

LIB_HEREDOC_START = "cat <<'FETCH_KUBECONFIG_LIB' > \"$HOME/.kube/lib/fetch-kubeconfig.sh\""
LIB_HEREDOC_END = "FETCH_KUBECONFIG_LIB"


def _load_steps():
    with open(YAML_PATH, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc["steps"]


def _step_script(steps, display_name):
    for step in steps:
        if step.get("displayName") == display_name:
            return step["script"]
    raise AssertionError(f"no step with displayName={display_name!r} found in {YAML_PATH}")


def _raw_get_credentials_invocations(script):
    """Lines that actually INVOKE `az aks get-credentials` (as opposed to
    comments that merely mention it, e.g. explaining historical bugs or the
    MSAL token-cache race). A real invocation line, once leading whitespace
    is stripped, does not start with '#'."""
    return [
        line for line in script.splitlines()
        if "az aks get-credentials" in line and not line.strip().startswith("#")
    ]


def _extract_lib_body():
    """Pulls the exact fetch-kubeconfig.sh heredoc body out of the
    "Enumerate clustermesh clusters" step, so tests exercise the real
    committed helper rather than a copy that could drift from it."""
    steps = _load_steps()
    script = _step_script(steps, "Enumerate clustermesh clusters")
    pattern = re.escape(LIB_HEREDOC_START) + r"\n(.*?)\n\s*" + re.escape(LIB_HEREDOC_END) + r"\n"
    match = re.search(pattern, script, re.S)
    assert match, "fetch-kubeconfig.sh heredoc not found in 'Enumerate clustermesh clusters' step"
    return match.group(1)


# Fake `az` CLI: driven entirely by env vars so each test can script exactly
# the sequence of outcomes it wants from successive `az aks get-credentials`
# calls, without any real network/Azure dependency.
#
#   AZ_BEHAVIOR   comma-separated outcomes, one consumed per invocation
#                 (extra invocations beyond the list repeat the last entry):
#                   success    - writes a valid-looking kubeconfig to $KUBECONFIG, exit 0
#                   empty      - exit 0 but writes nothing (empty $KUBECONFIG)
#                   timeout    - simulates the build-74260 ServerTimeout: prints
#                                the Azure error text and exits 1
#                   structural - prints a structural Azure CLI error
#                                (ResourceNotFound) and exits 1
#   AZ_CALL_LOG   path to a file this fake `az` appends one line to per call
#                 (so tests can assert exact call counts)
FAKE_AZ = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -u
    if [ "${1:-}" != "aks" ] || [ "${2:-}" != "get-credentials" ]; then
      echo "fake az: unsupported invocation: $*" >&2
      exit 2
    fi
    log="${AZ_CALL_LOG:-}"
    count_file="${AZ_CALL_COUNT_FILE:?AZ_CALL_COUNT_FILE must be set}"
    n=0
    [ -f "$count_file" ] && n=$(cat "$count_file")
    n=$((n + 1))
    echo "$n" > "$count_file"
    if [ -n "$log" ]; then echo "call=$n args=$*" >> "$log"; fi

    behaviors="${AZ_BEHAVIOR:-success}"
    IFS=',' read -r -a arr <<< "$behaviors"
    idx=$((n - 1))
    if [ "$idx" -ge "${#arr[@]}" ]; then
      idx=$((${#arr[@]} - 1))
    fi
    behavior="${arr[$idx]}"

    case "$behavior" in
      success)
        cat > "$KUBECONFIG" <<KCEOF
    apiVersion: v1
    clusters:
    - cluster: {server: https://fake-$n.example.com:443}
      name: fake
    contexts:
    - context: {cluster: fake}
      name: fake-context
    current-context: fake-context
    KCEOF
        exit 0
        ;;
      empty)
        : > "$KUBECONFIG"
        exit 0
        ;;
      timeout)
        echo "Deployment failed. Correlation ID: aaaa. ServerTimeout: The server did not respond in time." >&2
        exit 1
        ;;
      structural)
        echo "ResourceNotFound: The Resource 'Microsoft.ContainerService/managedClusters/x' could not be found." >&2
        exit 1
        ;;
      forbidden)
        echo "AuthorizationFailed: The client does not have authorization to perform action." >&2
        exit 1
        ;;
      *)
        echo "fake az: unknown AZ_BEHAVIOR entry '$behavior'" >&2
        exit 2
        ;;
    esac
""")


class FetchKubeconfigHelperTestCase(unittest.TestCase):
    """Base class: writes the extracted helper + fake az to a temp dir and
    exposes a `_run()` that sources the helper and invokes a function."""

    @classmethod
    def setUpClass(cls):
        cls.lib_body = _extract_lib_body()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        td = self.tmp.name

        self.lib_path = os.path.join(td, "fetch-kubeconfig.sh")
        with open(self.lib_path, "w", encoding="utf-8") as f:
            f.write(self.lib_body)

        self.bin_dir = os.path.join(td, "bin")
        os.makedirs(self.bin_dir, exist_ok=True)
        fake_az_path = os.path.join(self.bin_dir, "az")
        with open(fake_az_path, "w", encoding="utf-8") as f:
            f.write(FAKE_AZ)
        st = os.stat(fake_az_path)
        os.chmod(fake_az_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        self.count_file = os.path.join(td, "az_call_count")
        self.call_log = os.path.join(td, "az_call_log")
        self.dest_kubeconfig = os.path.join(td, "mesh-1.config")

    def _run(self, call_expr, env_overrides=None, timeout_s=30):
        """Sources the helper then evaluates `call_expr` (a bash snippet),
        printing "RC=<n>" as the last line so the test can recover the
        function's return code even though `set -e` is NOT used here."""
        script = f'source "{self.lib_path}"\n{call_expr}\nrc=$?\necho "RC=$rc"\n'
        env = os.environ.copy()
        env["PATH"] = self.bin_dir + os.pathsep + env["PATH"]
        env["AZ_CALL_COUNT_FILE"] = self.count_file
        env["AZ_CALL_LOG"] = self.call_log
        # Keep tests fast: low bounded timeout + low backoff.
        env.setdefault("FETCH_KUBECONFIG_ATTEMPT_TIMEOUT_SECONDS", "5")
        env.setdefault("FETCH_KUBECONFIG_MAX_ATTEMPTS", "5")
        env.setdefault("FETCH_KUBECONFIG_BACKOFF_SECONDS", "0")
        env.setdefault("KUBECONFIG_VALIDATE_TIMEOUT_SECONDS", "5")
        if env_overrides:
            env.update(env_overrides)
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, env=env, check=False,
            timeout=timeout_s,
        )
        return result

    def _call_count(self):
        if not os.path.exists(self.count_file):
            return 0
        with open(self.count_file, "r", encoding="utf-8") as f:
            return int(f.read().strip() or "0")


class TestFetchKubeconfigRetrySuccess(FetchKubeconfigHelperTestCase):
    def test_transient_server_timeout_then_success(self):
        """First attempt hits the exact build-74260 ServerTimeout; second
        attempt succeeds. fetch_kubeconfig must retry and return 0."""
        result = self._run(
            'fetch_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "timeout,success"},
        )
        self.assertIn("RC=0", result.stdout, f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertEqual(self._call_count(), 2, "expected exactly 2 az invocations (1 failure + 1 success)")
        self.assertTrue(os.path.exists(self.dest_kubeconfig))
        with open(self.dest_kubeconfig, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("current-context: fake-context", content)
        # No leftover .tmp.* files from the failed first attempt.
        leftovers = [
            p for p in os.listdir(os.path.dirname(self.dest_kubeconfig))
            if p.startswith(os.path.basename(self.dest_kubeconfig) + ".tmp.")
        ]
        self.assertEqual(leftovers, [], f"temp files leaked: {leftovers}")

    def test_actionable_logging_present(self):
        """Attempt/backoff/failure messages are logged so a build's console
        output remains actionable (not just a bare failing exit code)."""
        result = self._run(
            'fetch_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "timeout,success"},
        )
        self.assertIn("attempt 1/5", result.stdout)
        self.assertIn("ServerTimeout", result.stdout + result.stderr)
        self.assertIn("retrying in", result.stdout)
        self.assertIn("updated atomically", result.stdout)


class TestFetchKubeconfigExhaustedRetries(FetchKubeconfigHelperTestCase):
    def test_all_attempts_fail_returns_nonzero_after_max_attempts(self):
        result = self._run(
            'fetch_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "timeout"},
        )
        self.assertIn("RC=1", result.stdout)
        self.assertEqual(self._call_count(), 5, "expected all 5 attempts to be used on persistent transient failure")
        self.assertIn("exhausted 5", result.stdout)
        self.assertFalse(os.path.exists(self.dest_kubeconfig), "destination must not be created on total failure")

    def test_empty_output_treated_as_failed_attempt(self):
        """az exiting 0 but producing an empty kubeconfig must NOT be
        treated as success (guards against silently adopting a bad file)."""
        result = self._run(
            'fetch_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "empty,success"},
        )
        self.assertIn("RC=0", result.stdout)
        self.assertEqual(self._call_count(), 2)
        self.assertIn("treating as a failed attempt", result.stdout)


class TestFetchKubeconfigStructuralFailFast(FetchKubeconfigHelperTestCase):
    def test_structural_resource_not_found_fails_without_exhausting_retries(self):
        result = self._run(
            'fetch_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "structural"},
        )
        self.assertIn("RC=1", result.stdout)
        self.assertEqual(self._call_count(), 1, "structural errors must fail fast on the first attempt, not retry")
        self.assertIn("structural error", result.stdout)
        self.assertIn("##vso[task.logissue type=error;]", result.stdout)

    def test_structural_authorization_failed_fails_without_exhausting_retries(self):
        result = self._run(
            'fetch_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "forbidden"},
        )
        self.assertIn("RC=1", result.stdout)
        self.assertEqual(self._call_count(), 1, "AuthorizationFailed/Forbidden must fail fast, not retry")


class TestFetchKubeconfigAtomicity(FetchKubeconfigHelperTestCase):
    def test_failed_attempt_never_corrupts_existing_kubeconfig(self):
        """A pre-existing good kubeconfig must survive a fetch_kubeconfig()
        call that ultimately fails all attempts (build 74260's core
        atomicity requirement: a failed refetch must not corrupt what was
        already there)."""
        sentinel = "GOOD-EXISTING-KUBECONFIG-CONTENT\ncurrent-context: good\n"
        with open(self.dest_kubeconfig, "w", encoding="utf-8") as f:
            f.write(sentinel)

        result = self._run(
            'fetch_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "timeout"},
        )
        self.assertIn("RC=1", result.stdout)
        with open(self.dest_kubeconfig, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), sentinel, "existing kubeconfig must be untouched after all attempts fail")
        leftovers = [
            p for p in os.listdir(os.path.dirname(self.dest_kubeconfig))
            if p.startswith(os.path.basename(self.dest_kubeconfig) + ".tmp.")
        ]
        self.assertEqual(leftovers, [], f"temp files leaked: {leftovers}")

    def test_successful_fetch_replaces_atomically_via_rename(self):
        """On success the destination is replaced via `mv` (rename), not
        truncated in place — verified indirectly by asserting no partial
        write is ever visible via a stale inode (the tmp file disappears and
        the destination's new content is the complete fake success doc)."""
        with open(self.dest_kubeconfig, "w", encoding="utf-8") as f:
            f.write("OLD-CONTENT\n")

        result = self._run(
            'fetch_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "success"},
        )
        self.assertIn("RC=0", result.stdout)
        with open(self.dest_kubeconfig, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("OLD-CONTENT", content)
        self.assertIn("current-context: fake-context", content)


class TestKubeconfigIsValidAndEnsureKubeconfig(FetchKubeconfigHelperTestCase):
    VALID_KUBECONFIG = textwrap.dedent("""\
        apiVersion: v1
        clusters:
        - cluster: {server: https://example.com:443}
          name: c
        contexts:
        - context: {cluster: c}
          name: existing-context
        current-context: existing-context
        kind: Config
    """)

    def test_existing_valid_kubeconfig_causes_no_refetch(self):
        with open(self.dest_kubeconfig, "w", encoding="utf-8") as f:
            f.write(self.VALID_KUBECONFIG)

        result = self._run(
            'ensure_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "success"},
        )
        self.assertIn("RC=0", result.stdout)
        self.assertEqual(self._call_count(), 0, "a valid existing kubeconfig must not trigger az aks get-credentials")
        self.assertIn("reusing existing valid kubeconfig", result.stdout)
        with open(self.dest_kubeconfig, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), self.VALID_KUBECONFIG, "existing valid kubeconfig must be untouched")

    def test_missing_kubeconfig_triggers_fetch(self):
        self.assertFalse(os.path.exists(self.dest_kubeconfig))
        result = self._run(
            'ensure_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "success"},
        )
        self.assertIn("RC=0", result.stdout)
        self.assertEqual(self._call_count(), 1)
        self.assertTrue(os.path.exists(self.dest_kubeconfig))

    def test_empty_kubeconfig_triggers_refetch(self):
        with open(self.dest_kubeconfig, "w", encoding="utf-8"):
            pass  # zero-byte file
        result = self._run(
            'ensure_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "success"},
        )
        self.assertIn("RC=0", result.stdout)
        self.assertEqual(self._call_count(), 1, "empty kubeconfig must be treated as invalid and refetched")

    def test_malformed_kubeconfig_triggers_refetch(self):
        with open(self.dest_kubeconfig, "w", encoding="utf-8") as f:
            f.write("{ not: valid kubeconfig ][ at all\n")
        result = self._run(
            'ensure_kubeconfig "test-rg" "mesh-1" "' + self.dest_kubeconfig + '"',
            env_overrides={"AZ_BEHAVIOR": "success"},
        )
        self.assertIn("RC=0", result.stdout)
        self.assertEqual(self._call_count(), 1, "malformed kubeconfig must be treated as invalid and refetched")

    def test_kubeconfig_is_valid_true_for_good_file(self):
        with open(self.dest_kubeconfig, "w", encoding="utf-8") as f:
            f.write(self.VALID_KUBECONFIG)
        result = self._run('kubeconfig_is_valid "' + self.dest_kubeconfig + '"')
        self.assertIn("RC=0", result.stdout)

    def test_kubeconfig_is_valid_false_for_missing_file(self):
        result = self._run('kubeconfig_is_valid "' + self.dest_kubeconfig + '"')
        self.assertIn("RC=1", result.stdout)


class TestFetchKubeconfigLibBashSyntax(unittest.TestCase):
    """The extracted heredoc body must itself be syntactically valid bash
    (it is written verbatim to a .sh file at runtime and later sourced)."""

    def test_lib_body_bash_syntax(self):
        lib_body = _extract_lib_body()
        result = subprocess.run(
            ["bash", "-n"],
            input=lib_body, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, f"bash -n failed: stderr={result.stderr}")

    def test_lib_defines_expected_functions(self):
        lib_body = _extract_lib_body()
        for fn in ("fetch_kubeconfig", "kubeconfig_is_valid", "ensure_kubeconfig"):
            self.assertIn(f"{fn}()", lib_body, f"expected function {fn}() to be defined in the helper")


class TestValidateResourcesStaticWiring(unittest.TestCase):
    """Static/textual checks on validate-resources.yml itself: every step
    that needs the kubeconfig-fetch helper sources it, the build-74260
    redundant unconditional `az aks get-credentials` call is gone, and every
    embedded `script:` block remains syntactically valid bash."""

    SOURCE_LINE = 'source "$HOME/.kube/lib/fetch-kubeconfig.sh"'

    def setUp(self):
        self.steps = _load_steps()

    def test_all_script_steps_have_valid_bash_syntax(self):
        template_expr_re = re.compile(r"\$\{\{[^}]*\}\}")
        for step in self.steps:
            script = step.get("script")
            if not script:
                continue
            # Neutralize Azure Pipelines template expressions (e.g.
            # ${{ parameters.regions[0] }}), which are not valid bash syntax
            # on their own but are expanded by ADO before the shell runs.
            script_bash = template_expr_re.sub("__TEMPLATE_EXPR__", script)
            result = subprocess.run(
                ["bash", "-n"],
                input=script_bash, capture_output=True, text=True, check=False,
            )
            self.assertEqual(
                result.returncode, 0,
                f"step {step.get('displayName')!r} failed bash -n: {result.stderr}",
            )

    def test_wait_for_apiserver_step_sources_helper_and_has_no_raw_get_credentials(self):
        script = _step_script(self.steps, "Wait for clustermesh-apiserver Deployments + LBs (parallel)")
        self.assertIn(self.SOURCE_LINE, script)
        self.assertEqual(
            _raw_get_credentials_invocations(script), [],
            "no line should directly invoke `az aks get-credentials` outside the sourced helper",
        )
        self.assertIn("fetch_kubeconfig ", script)

    def test_wait_for_apiserver_prefetch_loop_is_still_sequential(self):
        """The initial prefetch loop must remain a plain sequential `for`
        loop (no backgrounding `&`) to avoid the shared MSAL token-cache
        race documented in the surrounding comments."""
        script = _step_script(self.steps, "Wait for clustermesh-apiserver Deployments + LBs (parallel)")
        m = re.search(
            r"for row in \$\(echo \"\$clusters\" \| jq -c '\.\[\]'\); do\n(.*?)\ndone",
            script, re.S,
        )
        self.assertIsNotNone(m, "sequential prefetch loop not found")
        loop_body = m.group(1)
        self.assertIn("fetch_kubeconfig", loop_body)
        self.assertNotRegex(loop_body, r"fetch_kubeconfig[^\n]*&\s*$",
                             "prefetch loop must not background fetch_kubeconfig calls")

    def test_validate_cilium_step_sources_helper_and_has_no_raw_get_credentials(self):
        script = _step_script(self.steps, "Validate Cilium + ClusterMesh on every cluster")
        self.assertIn(self.SOURCE_LINE, script)
        self.assertEqual(
            _raw_get_credentials_invocations(script), [],
            "build-74260 redundant unconditional az aks get-credentials invocation must be removed",
        )
        self.assertIn("ensure_kubeconfig ", script)

    def test_validate_cilium_per_cluster_loop_uses_ensure_kubeconfig(self):
        script = _step_script(self.steps, "Validate Cilium + ClusterMesh on every cluster")
        idx = script.index('echo "  Validating $role ($name)"')
        following = script[idx:idx + 2000]
        self.assertIn("ensure_kubeconfig \"$rg\" \"$name\" \"$kubeconfig\"", following)

    def test_enumerate_clusters_step_writes_the_helper_library(self):
        script = _step_script(self.steps, "Enumerate clustermesh clusters")
        self.assertIn(LIB_HEREDOC_START, script)
        self.assertIn("fetch_kubeconfig()", script)
        self.assertIn("kubeconfig_is_valid()", script)
        self.assertIn("ensure_kubeconfig()", script)


if __name__ == "__main__":
    unittest.main()
