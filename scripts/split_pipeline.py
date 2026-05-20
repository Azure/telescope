#!/usr/bin/env python3
"""Split a large Azure DevOps pipeline YAML into smaller files using template references.

Uses a bottom-up tree approach: builds a size tree mirroring the pipeline structure,
finds the deepest oversized subtree, and greedily extracts items into template files.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from enum import Enum

import yaml

DEFAULT_MAX_SIZE = 1_048_576  # 1 MB
MAX_FILES = 100

class Key(str, Enum):
    STAGES = "stages"
    JOBS = "jobs"
    STEPS = "steps"

    def __str__(self) -> str:
        return self.value


def yaml_size(data) -> int:
    """Return the size in bytes of the YAML representation of data."""
    return len(yaml.dump(data, default_flow_style=False).encode("utf-8"))


def write_yaml(path: str, data) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


class SplitError(Exception):
    pass


@dataclass
class SizeNode:
    """A node in the size tree mirroring the pipeline YAML structure."""
    size: int                                # yaml_size of this subtree
    data: dict | list                        # the actual YAML data at this node
    key: str | None = None                   # "stages", "jobs", or "steps" if this node has a splittable list
    children: list["SizeNode"] = field(default_factory=list)  # children for list items


def _build_size_tree(data: dict) -> SizeNode:
    """Build a SizeNode tree from pipeline YAML data."""
    node = SizeNode(size=yaml_size(data), data=data)

    # Find the first splittable key at this level
    for key in Key:
        key_str = str(key)
        if key_str in data and isinstance(data[key_str], list) and len(data[key_str]) > 0:
            node.key = key_str
            for item in data[key_str]:
                if isinstance(item, dict):
                    child = _build_size_tree(item)
                else:
                    child = SizeNode(
                        size=yaml_size({key_str: [item]}),
                        data=item,
                    )
                node.children.append(child)
            break  # only process the first splittable key

    return node



def _find_deepest_oversized(node: SizeNode, max_size: int) -> SizeNode | None:
    """Find the deepest node in the tree whose size exceeds max_size and has >1 children.

    Descends through single-child containers and into oversized children first.
    """
    if node.key is None or len(node.children) == 0:
        return None

    # Single-child container: descend through it (e.g. 1 stage with many jobs)
    if len(node.children) == 1:
        return _find_deepest_oversized(node.children[0], max_size)

    # Multiple children: check if any single child is oversized and splittable
    for child in node.children:
        if child.size > max_size and child.key is not None:
            deeper = _find_deepest_oversized(child, max_size)
            if deeper is not None:
                return deeper
            return child

    # No single child is oversized with further splittable children.
    # If this node is oversized split here.
    if node.size > max_size:
        return node

    return None


class PipelineSplitter:
    def __init__(self, max_size_bytes: int = DEFAULT_MAX_SIZE, max_files: int = MAX_FILES, repo_root: str = ""):
        assert repo_root, "repo_root must be a non-empty string"

        self.max_size_bytes: int = max_size_bytes
        self.max_files: int = max_files
        self.repo_root: str = os.path.abspath(repo_root)
        self.created_files: list[str] = []
        self.file_counter: int = 0

    def split(self, filepath: str) -> list[str]:
        """Split a pipeline YAML file. Returns list of all created files."""
        filepath = os.path.abspath(filepath)

        with open(filepath) as f:
            root_data = yaml.safe_load(f)

        self.created_files = []
        self.file_counter = 0
        
        """Split a file using the SizeTree approach."""
        if yaml_size(root_data) <= self.max_size_bytes:
            raise SplitError(
                f"Error: file '{filepath}' is already under {self.max_size_bytes} bytes, no split needed."
            )

        dir_path = os.path.dirname(filepath)
        stem = os.path.splitext(os.path.basename(filepath))[0]

        # Build size tree
        tree = _build_size_tree(root_data)

        # Iteratively extract until the file fits
        while tree.size > self.max_size_bytes:            
            target = _find_deepest_oversized(tree, self.max_size_bytes)

            if target is None:
                # No splittable node found — check if a single unsplittable element is too large
                self._cleanup_created_files()
                raise SplitError(
                    f"Error: cannot split further. A single element in '{filepath}' "
                    f"exceeds {self.max_size_bytes} bytes."
                )

            # Heuristic pack: find first n items whose cumulative size exceeds max_bytes
            key = target.key
            children = target.children
            items = target.data[key]

            cumulative = 2 + len(key) # account for key and list structure in YAML
            # Default to put all children in a template if they all fit in max size.
            split_index = len(children)
            for i in range(len(children)):
                # Size of this item wrapped in a list: approximate with child.size
                item_size = yaml_size([items[i]])
                cumulative += item_size
                if cumulative > self.max_size_bytes:
                    split_index = i
                    break

            # If first item alone exceeds the limit, extract it by itself
            if split_index == 0:
                split_index = 1

            # Extract items 0 to split_index-1 (the largest split_index that fit)
            extract_count = split_index  # extract items[0..split_index-1]
            extracted_items = items[:extract_count]
            remaining_items = items[extract_count:]

            # Guard: if all extracted items are already template refs, splitting won't help
            if all(isinstance(item, dict) and "template" in item for item in extracted_items):
                self._cleanup_created_files()
                raise SplitError(
                    f"Error: cannot split further. A single element in '{filepath}' "
                    f"exceeds {self.max_size_bytes} bytes."
                )

            # Write extracted items to a new file
            part_path = self._next_filename(dir_path, stem)
            part_data = {key: extracted_items}
            write_yaml(part_path, part_data)

            self.created_files.append(part_path)
            if len(self.created_files) > self.max_files:
                self._cleanup_created_files()
                raise SplitError(
                    f"Error: splitting produced {len(self.created_files)} files, "
                    f"exceeding the limit of {self.max_files}."
                )

            # Update the data: replace extracted items with template ref
            template_path = os.path.relpath(part_path, self.repo_root)
            
            template_ref = {"template": f"$(Pipeline.Workspace)/s/{template_path}"}
            target.data[key] = [template_ref] + remaining_items

            # TODO: Instead of rebuilding the entire tree, update sizes incrementally.
            tree = _build_size_tree(tree.data)

        # Write the final (now small enough) file
        part_path = os.path.join(dir_path, f"{stem}_0.yaml")
        write_yaml(part_path, tree.data)
        self.created_files.append(part_path)

        return self.created_files

    def _next_filename(self, dir_path: str, stem: str) -> str:
        """Generate the next unique split filename."""
        self.file_counter += 1
        name = f"{stem}_{self.file_counter}.yaml"
        return os.path.join(dir_path, name)

    def _cleanup_created_files(self) -> None:
        """Remove all files created during splitting."""
        for f in self.created_files:
            if os.path.exists(f):
                os.remove(f)
        self.created_files.clear()


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
    parser.add_argument(
        "--repo-root",
        type=str,
        required=True,
        help="Root of the repo. Template paths will be relative to this directory.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"Error: file '{args.filepath}' not found.", file=sys.stderr)
        sys.exit(1)

    splitter = PipelineSplitter(max_size_bytes=args.max_size, max_files=args.max_files, repo_root=args.repo_root)
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
