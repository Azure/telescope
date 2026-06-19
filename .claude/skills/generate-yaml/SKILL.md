---
name: generate-yaml
description: Generate pipeline YAML from KCL source
---

# Generate pipeline YAML from KCL source

## Validate scenarios first

Before generating, run the cross-scenario validation gate. It catches the one
thing KCL's compiler cannot see: **path-string references** between scenarios
(one scenario's `cl2Manifest` / `kwokNodeManifest` pointing into another
scenario's directory) that form a loop. KCL already rejects circular *imports*
on its own, so this gate deliberately does not re-check those.

```bash
python3 scripts/validate_scenarios.py
```

On success it prints `validate_scenarios: OK ...` and exits 0. If it fails
(exit 1), it prints the offending cycle (`a -> b -> a`); fix the path-string
references before continuing.

## Generate

Given a pipeline KCL file (e.g. `path/to/pipeline.k`), determine its directory and run:

```bash
kcl run <path/to/pipeline.k> -S output -o <path/to/pipeline.yaml>
```

The output YAML file is written alongside the KCL source file in the same directory.

**Example:** for `kcl/example_pipeline/pipeline.k`:
```bash
kcl run kcl/example_pipeline/pipeline.k -S output -o kcl/example_pipeline/pipeline.yaml
```

### If `kcl run` reports a circular import

KCL fails fast with `error[E1001] RecursiveLoad` / `circular reference between
modules ...` when scenarios import each other in a loop. To reframe that raw
diagnostic in scenario terms for the author, pass the captured stderr through:

```python
from scripts.validate_scenarios import format_kcl_cycle_error
print(format_kcl_cycle_error(stderr))  # None if stderr is not a RecursiveLoad
```

## Split if oversized

Azure DevOps enforces a 2 MB limit on a single pipeline YAML file. After generating the YAML, check its size:

```bash
stat -c %s <path/to/pipeline.yaml>
```

If the size exceeds 2 MB (2097152 bytes), split it with `scripts/split_pipeline.py`, passing the repo root so template references are emitted with paths relative to it:

```bash
python3 scripts/split_pipeline.py <path/to/pipeline.yaml> --repo-root .
```

The script rewrites the original file and creates sibling `*_N.yaml` template files alongside it.
