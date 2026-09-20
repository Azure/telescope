# Wonderyl's Style Guide

Conventions distilled from review comments by [@wonderyl](https://github.com/wonderyl)
on pull requests targeting the `v2` branch of `Azure/telescope`. Only preferences that
recur, or that were stated as general principles, are recorded here — one-off factual
corrections are omitted.

---

# Reuse & Abstraction

## Only wrap a command in a helper when the helper encapsulates something

A lambda that passes every argument straight through to `az …` adds indirection without
simplifying anything — callers should use `AzCli` with the script directly. When writing a
function, be able to answer: *what does this function encapsulate?* *(PR [#1197](https://github.com/Azure/telescope/pull/1197), [#1196](https://github.com/Azure/telescope/pull/1196))*

## Build abstractions on actual use cases, not hypothetical use cases

Speculative options are dropped until a real caller needs them. A "generic" helper whose
semantics differ per scenario should be split into narrowly named functions instead.
*(PR [#1234](https://github.com/Azure/telescope/pull/1234))*

## Show a real call site when adding a lib function

"How do you use this function?" is asked of every lib step landed without a visible
consumer. A call site proves the interface is right and often reveals that several steps
should be bundled. *(PR [#1197](https://github.com/Azure/telescope/pull/1197), [#1199](https://github.com/Azure/telescope/pull/1199))*

## Reuse existing in-repo tooling instead of writing ad-hoc equivalents

Check whether an already-wrapped tool covers the need before adding a bespoke client or
script. *(PR [#1316](https://github.com/Azure/telescope/pull/1316): "you can use kperf, right?"; PR [#1127](https://github.com/Azure/telescope/pull/1127): "You can use run id instead,
there's a step for it.")*

---

# Naming & Structure

## Do not introduce a new concept when a domain concept already covers it

Inventing parallel vocabulary (a "group" alongside KWOK's existing "controller") raises
cognitive load for readers who already know the underlying system. Reuse the upstream term.
*(PR [#1103](https://github.com/Azure/telescope/pull/1103))*

## Name booleans so they read as booleans

Use a `use_` / `enable_` / `is_` / `has_` prefix so the type is obvious at the call site.
*(PR [#1103](https://github.com/Azure/telescope/pull/1103): `use_multiple_controllers`)*

## Make names reflect exactly what the thing does

A helper that does work outside the scope its name suggests must be renamed or have that
work moved out. Drop vendor/marketing words that carry no information
(`InstallKubePrometheusStack` → `InstallPrometheus`). A condition named `error_rate_too_high`
that fires on any loss > 0 needs a real threshold or a truthful name.
*(PR [#1103](https://github.com/Azure/telescope/pull/1103), [#1237](https://github.com/Azure/telescope/pull/1237), [#1184](https://github.com/Azure/telescope/pull/1184), [#1234](https://github.com/Azure/telescope/pull/1234))*

## Avoid abbreviations; qualify ambiguous parameter names

Spell identifiers out (`FWPRIVATE_IP` → firewall private IP) and qualify names that are
ambiguous across similar objects (`vm_sku` → `runner_vm_sku`). *(PR [#1198](https://github.com/Azure/telescope/pull/1198), [#1313](https://github.com/Azure/telescope/pull/1313))*

## Use correct, conventional unit names

`GiB` and `B` are for bytes, not bits. A wrong unit in a size parameter is a correctness
hazard, not a cosmetic one. *(PR [#1151](https://github.com/Azure/telescope/pull/1151))*

## Do not prefix names with an underscore in KCL

Nothing is exported in these files, so the private-by-convention underscore is pure noise.
*(PR [#1151](https://github.com/Azure/telescope/pull/1151), [#1164](https://github.com/Azure/telescope/pull/1164), [#1217](https://github.com/Azure/telescope/pull/1217))*

## Group functions that are always used together

Discoverability beats strict taxonomy. `runkperf` and `collectKperfResult` are always used
together, so they belong in one `kperf/` folder even though one shells out to `az`.
*(PR [#1184](https://github.com/Azure/telescope/pull/1184), [#1296](https://github.com/Azure/telescope/pull/1296))*

## Place modules by the domain they belong to, and keep layers clean

A step that is fundamentally about Kubernetes belongs under `lib/steps/k8s` (or a dedicated
`health/` package) even if it happens to use the Azure CLI, since it can be adapted to other
clouds. A cloud-agnostic layer must not import a cloud-specific one. *(PR [#1296](https://github.com/Azure/telescope/pull/1296), [#1184](https://github.com/Azure/telescope/pull/1184))*

## Keep file names consistent between definition and consumption

A config must not be renamed between its repo path and its mount path, and two different
files must not share a name. *(PR [#1131](https://github.com/Azure/telescope/pull/1131), [#1127](https://github.com/Azure/telescope/pull/1127))*

## Keep names, values, and scope consistent with the PR's stated intent

A folder named for a 15K-node run should not ship constants for 100 nodes.
*(PR [#1217](https://github.com/Azure/telescope/pull/1217))*

---

# KCL / Pipeline Authoring

## Only introduce a name when the value is used more than once

Single-use constants, variables, and helper lambdas force the reader to jump to the top of
the file with no IDE support — inline them. Constants used repeatedly *are* preferred; a
little literal repetition at call sites is acceptable when it keeps the value visible.
Avoid constants that merely alias a pipeline variable. *(PR [#1184](https://github.com/Azure/telescope/pull/1184), [#1217](https://github.com/Azure/telescope/pull/1217), [#1313](https://github.com/Azure/telescope/pull/1313), [#1127](https://github.com/Azure/telescope/pull/1127))*

## Always annotate lambda return types, but never widen them

The return type of a lambda is required. Declare exactly what is returned — `ap.Stage`, not
`ap.Stage | ap.Template`. *(PR [#1184](https://github.com/Azure/telescope/pull/1184), [#1164](https://github.com/Azure/telescope/pull/1164))*

## Omit same-folder imports

KCL files in the same directory are in the same namespace, thus is already visible to each other.
*(PR [#1164](https://github.com/Azure/telescope/pull/1164), [#1151](https://github.com/Azure/telescope/pull/1151))*

## Import the package, not each file, and drop redundant prefixes and aliases

`import lib.steps.health` then `health.ValidateAzureCNS` — not one import per file. Omit
the `telescope.` prefix inside the telescope repo, and omit `as X` aliases that restate the
module name. *(PR [#1313](https://github.com/Azure/telescope/pull/1313))*

## Order parameters by importance; defaults and variadics last

Arguments the caller must always specify come first; optional or debug knobs come last with
sensible defaults; an open-ended `params` map goes at the very end. Keep semantically
paired parameters adjacent. *(PR [#1313](https://github.com/Azure/telescope/pull/1313), [#1184](https://github.com/Azure/telescope/pull/1184), [#1155](https://github.com/Azure/telescope/pull/1155), [#1312](https://github.com/Azure/telescope/pull/1312))*

## Define each default value in exactly one place

Repeating a default across the KCL signature, the Python signature, and argparse means
changing one silently has no effect. *(PR [#1155](https://github.com/Azure/telescope/pull/1155))*

## Choose the default that matches the dominant call site

If nearly every caller passes the same non-default value, flip the default rather than
repeating it everywhere. *(PR [#1313](https://github.com/Azure/telescope/pull/1313): "should continueOnError default to True instead?")*

## Do not allow caller of a function to set contradicting parameters.

When one argument is purely a function of another, compute it inside the lambda so call
sites cannot pass an inconsistent pair. Likewise, don't add a `stepName` parameter beside an
existing `name` used as `displayName`. *(PR [#1184](https://github.com/Azure/telescope/pull/1184), [#1221](https://github.com/Azure/telescope/pull/1221))*

## Enforce argument constraints with `assert`, not comments

Mutual exclusion, required-one-of, and contradictory pairs must be encoded as a KCL
`assert` with a clear message — the compiler will not enforce comments. *(PR [#1312](https://github.com/Azure/telescope/pull/1312), [#1299](https://github.com/Azure/telescope/pull/1299))*

## Use union types and schemas instead of stringly-typed asserts and bare dicts

Constrain enumerated parameters with `kind: "deployment" | "job" | …`, and model structured
data with a `schema` rather than a `{str:str}` map whose keys are undiscoverable.
*(PR [#1234](https://github.com/Azure/telescope/pull/1234), [#1228](https://github.com/Azure/telescope/pull/1228))*

## Don't conspire between two functions

When one step writes a file and a later step reads it, a hardcoded path is an invisible
contract. Take it as a parameter with a default. *(PR [#1184](https://github.com/Azure/telescope/pull/1184); kperf steps now take
`resultPath` and `kubeconfig`)*

## Keep related manifests in one multi-document YAML file

Splitting a ConfigMap, Job, and test config into separate files for the same workload adds
indirection with no benefit. *(PR [#1127](https://github.com/Azure/telescope/pull/1127), [#1131](https://github.com/Azure/telescope/pull/1131))*

## Hoist repeated literals such as image references into shared constants

Versioned images recur across steps and must be upgraded together — put them in `lib/const`.
*(PR [#1286](https://github.com/Azure/telescope/pull/1286); `lib/const.k` defines `BUSYBOX_IMAGE`)*

## Reference only official, published artifact versions

Personal forks and dev-tagged images in checked-in pipelines are unreproducible and can
disappear. *(PR [#1313](https://github.com/Azure/telescope/pull/1313))*

## Prefer checked-in pipelines and stages over runtime parameters

Parameters make reruns easy but leave the actual settings of past runs out of git. Encode
each distinct configuration as its own pipeline or stage so the reader can see what was run.
*(PR [#1313](https://github.com/Azure/telescope/pull/1313))*

## Justify the cost of triggers and schedules

Large perf pipelines create whole AKS clusters per fire. Leave `trigger` off (manual) by
default, and defend any cron cadence with a reason to track that often. *(PR [#1127](https://github.com/Azure/telescope/pull/1127), [#1184](https://github.com/Azure/telescope/pull/1184))*

## Record start and end timestamps around benchmark phases

Benchmark stages emit start/end times as pipeline variables so results correlate with
dashboards and telemetry. *(PR [#1316](https://github.com/Azure/telescope/pull/1316); `PrintAsiDashboardUrl` consumes `$(BENCHMARK_START_TIME)`)*

## Put one argument or field per line

Multi-argument step invocations and multi-field struct literals should break one item per line.
*(PR [#1217](https://github.com/Azure/telescope/pull/1217), [#1183](https://github.com/Azure/telescope/pull/1183))*

---

# Shell Scripting

## Fail loudly instead of defaulting missing values

Substituting a default for an absent `kubectl`/`az` query result (`completions=1`, `ready=0`)
turns a broken query into a passing check. Print an error and exit — the result is unusable
anyway. *(PR [#1234](https://github.com/Azure/telescope/pull/1234))*

## Make failure markers distinctive enough to grep

`FAIL:` collides with unrelated tool output in pipeline logs; use something like
`FAILED WORKLOAD CHECK:`. *(PR [#1234](https://github.com/Azure/telescope/pull/1234))*

## Query the API once and analyze the snapshot locally

Per-object `kubectl get` in a loop is slow at scale and races with object churn. Dump all
required state into one JSON document (or use the controller's own status counts) and
evaluate from that. *(PR [#1252](https://github.com/Azure/telescope/pull/1252), [#1281](https://github.com/Azure/telescope/pull/1281))*

## Branch on specific conditions explicitly; never leave the specific case as the fallthrough

Treating one known error as the implicit default forces a restructure the moment a second
case appears. Enumerate conditions. *(PR [#1213](https://github.com/Azure/telescope/pull/1213))*

## Factor shared logic into functions rather than duplicating branches

A nested/duplicated `case` used to reuse a block should be a helper function, letting a
single flat dispatch stay readable. *(PR [#1234](https://github.com/Azure/telescope/pull/1234))*

## Declare variables at first use, not up front

Pre-declaring locals at the top separates the name from its meaning, and a variable assigned
in many branches but read dozens of lines below is hard to follow. *(PR [#1234](https://github.com/Azure/telescope/pull/1234))*

## Don't include any of the AI generate code that you don't understand

Keep only what you can explain; Delete unnecssaray comment, but keep non-obvious ones. *(PR [#1281](https://github.com/Azure/telescope/pull/1281), [#1286](https://github.com/Azure/telescope/pull/1286), [#1285](https://github.com/Azure/telescope/pull/1285), [#1184](https://github.com/Azure/telescope/pull/1184))*

## Make checks strict
Assert the full expected pattern e.g. a complete IP, not its first octet. *(PR [#1285](https://github.com/Azure/telescope/pull/1285)*

## Format generated CLI invocations one argument per line

Emit `az` commands with backslash continuations, one `--argument` per line, including
conditionally-included ones. They are called "arguments", matching the Azure CLI's own
terminology. Keep continuation indentation aligned. *(PR [#1196](https://github.com/Azure/telescope/pull/1196), [#1183](https://github.com/Azure/telescope/pull/1183), [#1313](https://github.com/Azure/telescope/pull/1313))*

## Use descriptive identifiers in generated shell

Single-character tokens embedded in resource names or command arguments are unreadable in
pipeline logs. *(PR [#1151](https://github.com/Azure/telescope/pull/1151): "What does `x` stand for?")*

---

# Error Handling & Reliability

## Do not let `continueOnError` or retries mask genuine failures

Swallowing errors to keep a pipeline green destroys the signal the benchmark exists to
produce. If a step may fail benignly, the real failure must remain distinguishable.
*(PR [#1127](https://github.com/Azure/telescope/pull/1127))*

## Fail loudly on invalid input instead of silently defaulting

`getattr(logging, level.upper(), logging.INFO)` hides typos in user config — raise instead.
*(PR [#1165](https://github.com/Azure/telescope/pull/1165))*

## Do not produce artifacts nobody consumes

A file written but never uploaded is dead code: wire it up or delete it. *(PR [#1184](https://github.com/Azure/telescope/pull/1184))*

## Justify retries and workarounds with concrete detail

"Retried because transient" must say *which* operations and *why*, so the workaround can be
re-evaluated later. *(PR [#1213](https://github.com/Azure/telescope/pull/1213))*

---

# Python

## Expose configuration as CLI arguments, not environment variables

Env-var-only knobs are hidden backdoors that never show up in `-h`, so other users cannot
discover them. *(PR [#1127](https://github.com/Azure/telescope/pull/1127))*

## Check what the stdlib already accepts before writing conversion code

`logging.setLevel` already accepts string level names — read the docs before adding adapter
logic. *(PR [#1165](https://github.com/Azure/telescope/pull/1165))*

---

# Testing

## Unit-test your own code, not third-party libraries

Asserting that a vendor SDK behaves as documented adds no signal. Test the function of yours
that calls into it. *(PR [#1143](https://github.com/Azure/telescope/pull/1143))*

## Mock the external dependency, not your own functions

Patch the boundary that needs real infrastructure (e.g. the k8s client) so the surrounding
logic is actually exercised. *(PR [#1103](https://github.com/Azure/telescope/pull/1103))*

## Write KCL tests for non-trivial logic

Any helper with real computation — such as splitting node counts across pools — gets a
`kcl test`. *(PR [#1183](https://github.com/Azure/telescope/pull/1183); `kcl/lib/steps/azure/plan_node_pools_test.k`)*

## Assert exact values, uniformly, in every test

Pin down exact per-element values (names, SKUs, counts) rather than aggregates like a sum
that many wrong outputs would satisfy — and apply the same strictness to every test in the
file, since loose assertions are the easy failure mode for AI-generated tests. *(PR [#1183](https://github.com/Azure/telescope/pull/1183))*

---

# Azure / Infrastructure

## Prefer the first-class `az` command over raw REST calls

Inline `az rest` PUTs with long JSON bodies bypass CLI validation and reusable lib steps.
They are only justified while a feature is unreleased; once the CLI supports it, switch to
`az aks create` or extend the lib helper. Prefer configuring at creation time over patching
afterwards. *(PR [#1217](https://github.com/Azure/telescope/pull/1217), [#1184](https://github.com/Azure/telescope/pull/1184), [#1198](https://github.com/Azure/telescope/pull/1198))*

## Minimize and justify permissions, scopes, and allowlists

Don't assign overlapping roles or repeat an assignment per-subnet when a resource-group
scope suffices, and don't copy in firewall FQDN rules that are redundant supersets. Every
grant must be needed and understood. *(PR [#1217](https://github.com/Azure/telescope/pull/1217))*

## Avoid static secrets

Generating a random credential at provisioning time and storing it in Key Vault beats a
caller-supplied password variable. *(PR [#1228](https://github.com/Azure/telescope/pull/1228))*

---

# Documentation

## Write comments that convey intent, not comments that restate the code

Restating the code creates maintenance work on every change. Reserve comments for intent,
non-obvious algorithms, and implicit contracts. *(PR [#1183](https://github.com/Azure/telescope/pull/1183))*

## Comment every non-obvious number and design choice

Magic values — replica counts, QPS, completions, sizing — need their reasoning in the file
the reader will actually be looking at, with a pointer to the source they were derived from.
Inconsistent values across sibling configs need explicit justification.
*(PR [#1326](https://github.com/Azure/telescope/pull/1326), [#1131](https://github.com/Azure/telescope/pull/1131), [#1127](https://github.com/Azure/telescope/pull/1127))*

## Leave a TODO when landing a known-temporary workaround

Fragile manifest patching, images built from unmerged branches, and similar acknowledged
shortcuts carry a TODO so the debt stays visible. *(PR [#1103](https://github.com/Azure/telescope/pull/1103), [#1151](https://github.com/Azure/telescope/pull/1151))*

## Make implicit pipeline outputs explicit

Steps that export values via `task.setvariable` are undeclared side channels; declare
outputs so consumers can be verified. *(PR [#1221](https://github.com/Azure/telescope/pull/1221))*

---

# PR Hygiene

## Regenerate and commit all pipeline YAMLs when KCL libs change

The YAML is a generated artifact checked into the repo via a git hook. After changing a
shared lib, regenerate *every* pipeline so the blast radius is visible in the diff — and
state whether an existing pipeline's output changed. *(PR [#1151](https://github.com/Azure/telescope/pull/1151), [#1184](https://github.com/Azure/telescope/pull/1184), [#1246](https://github.com/Azure/telescope/pull/1246), [#1201](https://github.com/Azure/telescope/pull/1201), [#1112](https://github.com/Azure/telescope/pull/1112))*

## Scrutinise every line rather than following the existing pattern

Copying nearby code — or letting an AI extend it — propagates mistakes. Authors are expected
to explain each line, including where every referenced variable is defined.
*(PR [#1217](https://github.com/Azure/telescope/pull/1217): "This is exactly why we need to scrutinise every line of code, someone or AI may
'just follow' the code and pattern.")*

## Defer parts that cannot be reviewed yet

Split out code whose correctness depends on content not yet present into a follow-up PR, so
each change can be judged on its own. *(PR [#1313](https://github.com/Azure/telescope/pull/1313), [#1296](https://github.com/Azure/telescope/pull/1296))*
