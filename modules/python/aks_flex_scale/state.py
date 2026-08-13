"""Durable run state and event recording."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunState:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.events_path = self.directory / "events.jsonl"
        self.lock = threading.Lock()
        self.data: dict[str, Any] = {
            "schemaVersion": 1, "nodes": {}, "resources": {}, "versions": {}, "phases": {}
        }
        if self.path.exists():
            with self.path.open(encoding="utf-8") as handle:
                self.data = json.load(handle)
        self.data.setdefault("phases", {})

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def save(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    def event(self, kind: str, **fields: Any) -> None:
        with self.lock:
            record = {"time": self.now(), "kind": kind, **fields}
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            if "node" in fields:
                node = self.data["nodes"].setdefault(fields["node"], {})
                node.update({key: value for key, value in fields.items() if key != "node"})
                node["lastEvent"] = kind
                node["lastUpdate"] = record["time"]
            self.save()

    def nodes_event(self, kind: str, nodes: list[str], **fields: Any) -> None:
        with self.lock:
            timestamp = self.now()
            record = {"time": timestamp, "kind": kind, "nodes": nodes, **fields}
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            for name in nodes:
                node = self.data["nodes"].setdefault(name, {})
                node.update(fields)
                node["lastEvent"] = kind
                node["lastUpdate"] = timestamp
            self.save()

    def set_resource(self, key: str, value: Any) -> None:
        with self.lock:
            self.data["resources"][key] = value
            self.save()

    def set_versions(self, value: dict[str, str]) -> None:
        with self.lock:
            self.data["versions"] = value
            self.save()
