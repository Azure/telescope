---
name: generate-yaml
description: Generate pipeline YAML from KCL source
---

# Generate pipeline YAML from KCL source

Given a pipeline KCL file (e.g. `path/to/pipeline.k`), determine its directory and run:

```bash
kcl run <path/to/pipeline.k> -S output -o <path/to/pipeline.yaml>
```

The output YAML file is written alongside the KCL source file in the same directory.

**Example:** for `kcl/example_pipeline/pipeline.k`:
```bash
kcl run kcl/example_pipeline/pipeline.k -S output -o kcl/example_pipeline/pipeline.yaml
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
