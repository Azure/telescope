#!/usr/bin/env python3
"""Split a large Azure DevOps pipeline YAML into smaller files using template references."""

import argparse
import copy
import os
import sys
from enum import Enum

import yaml

DEFAULT_MAX_SIZE = 1_048_576  # 1 MB
MAX_FILES = 100

SPLIT_KEYS = ("stages", "jobs", "steps")


class Key(str, Enum):
    STAGES = "stages"
    JOBS = "jobs"
    STEPS = "steps"

    def __str__(self) -> str:
        return self.value


def yaml_size(data: dict) -> int:
    """Return the size in bytes of the YAML representation of data."""
    return len(yaml.dump(data, default_flow_style=False).encode("utf-8"))


def write_yaml(path: str, data: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


class SplitError(Exception):
    pass


def _find_splittable(data: dict) -> tuple[list[str | int], str, list] | None:
    """Find the first splittable list in data, traversing stages > jobs > steps.

    Returns (path_to_parent, key, items) where path_to_parent is a list of
    keys/indices to reach the dict containing the splittable list, or None.
    """
    for key in SPLIT_KEYS:
        if key in data and isinstance(data[key], list):
            items = data[key]
            if len(items) > 1:
                return ([], key, items)
            # Single item — look deeper inside it
            if len(items) == 1 and isinstance(items[0], dict):
                result = _find_splittable(items[0])
                if result:
                    inner_path, inner_key, inner_items = result
                    return ([key, 0] + inner_path, inner_key, inner_items)
    return None


class PipelineSplitter:
    def __init__(self, max_size_bytes: int = DEFAULT_MAX_SIZE, max_files: int = MAX_FILES):
        self.max_size_bytes = max_size_bytes
        self.max_files = max_files
        self.created_files: list[str] = []

    def split(self, filepath: str) -> list[str]:
        """Split a pipeline YAML file. Returns list of all created files."""
        filepath = os.path.abspath(filepath)

        with open(filepath) as f:
            data = yaml.safe_load(f)

        self.created_files = []
        self._split_file(filepath, data)

        return self.created_files

    def _split_file(self, filepath: str, data: dict) -> None:
        """Recursively split a YAML file until all parts are under the size limit."""
        if yaml_size(data) <= self.max_size_bytes:
            write_yaml(filepath, data)
            return

        result = _find_splittable(data)
        if result is None:
            raise SplitError(
                f"Error: cannot split further. A single element in '{filepath}' "
                f"exceeds {self.max_size_bytes} bytes."
            )

        path, key, items = result
        mid = len(items) // 2
        left, right = items[:mid], items[mid:]

        dir_path = os.path.dirname(filepath)
        stem = os.path.splitext(os.path.basename(filepath))[0]

        part1_name = f"{stem}_1.yaml"
        part2_name = f"{stem}_2.yaml"
        part1_path = os.path.join(dir_path, part1_name)
        part2_path = os.path.join(dir_path, part2_name)

        self.created_files.append(part1_path)
        self.created_files.append(part2_path)

        if len(self.created_files) > self.max_files:
            raise SplitError(
                f"Error: splitting produced {len(self.created_files)} files, "
                f"exceeding the limit of {self.max_files}."
            )

        # Recurse on part files
        self._split_file(part1_path, {key: left})
        self._split_file(part2_path, {key: right})

        # Rewrite this file with template references at the found path
        new_data = copy.deepcopy(data)
        target = new_data
        for step in path:
            target = target[step]
        target[key] = [
            {"template": part1_name},
            {"template": part2_name},
        ]
        write_yaml(filepath, new_data)


def main():
    parser = argparse.ArgumentParser(description="Split large pipeline YAML files")
    parser.add_argument("filepath", help="Path to the pipeline YAML file")
    parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE,
        help=f"Maximum file size in bytes (default: {DEFAULT_MAX_SIZE})",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=MAX_FILES,
        help=f"Maximum number of split files (default: {MAX_FILES})",
    )
    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"Error: file '{args.filepath}' not found.", file=sys.stderr)
        sys.exit(1)

    splitter = PipelineSplitter(max_size_bytes=args.max_size, max_files=args.max_files)
    try:
        created = splitter.split(args.filepath)
        if created:
            print(f"Split into {len(created)} part files:")
            for f in created:
                print(f"  {f}")
    except SplitError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
