---
name: generate_yaml
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
