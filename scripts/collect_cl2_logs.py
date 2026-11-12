"""Run CL2 with best-effort, bounded live log collection.

Initial/final tails, kubelet rotation, deleted pods and outages can lose logs.
Timestamp overlap deliberately duplicates lines; a successful Job never implies
complete logs. Only successfully written newline-terminated records advance the
cursor. Live request lifetime is bounded, not a connection-establishment timeout.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import re
import selectors
import signal
import subprocess
import sys
import threading
import time


def since_timestamp(timestamp):
    # Round down after the overlap, including RFC3339 nanosecond timestamps.
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)", timestamp):
        raise ValueError("not a timestamped log record")
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (value.astimezone(timezone.utc) - timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def kill_process(process, wait=True):
    # Every child starts a new session: never signal the agent's process group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if wait:
        process.wait(timeout=1)


class Collector:
    def __init__(self, args):
        self.args = args
        self.directory = Path(args.log_directory)
        self.stop = threading.Event()
        self.deadline = float("inf")
        self.exit_code = None
        self.workers = {}
        self.events = []
        self.lock = threading.Lock()
        self.partial = False
        self.job = None
        self.pods = None
        self.expected_pods = None

    def event(self, message, partial=True):
        with self.lock:
            self.partial |= partial
            entry = {"time": datetime.now(timezone.utc).isoformat(), "message": message}
            self.events.append(entry)
            self.events = self.events[-1000:]
            print(f"CL2 COLLECTION: {message}", file=sys.stderr, flush=True)
            try:
                with (self.directory / "collector-errors.log").open("a") as output:
                    output.write(json.dumps(entry) + "\n")
            except OSError as error:
                self.partial = True
                print(f"CL2 COLLECTION: cannot persist diagnostics: {error}", file=sys.stderr)

    def write_json(self, name, data):
        try:
            target = self.directory / name
            staging = target.with_suffix(".json.new")
            staging.write_text(json.dumps(data, indent=2) + "\n")
            staging.replace(target)
        except OSError as error:
            self.event(f"Cannot persist {name}: {error}")

    def save_status(self, finished=False):
        self.write_json("collection-status.json", {
            "status": ("partial" if self.partial else "best-effort") if finished else "collecting",
            "benchmarkExitCode": self.exit_code,
            "initialTailLines": self.args.tail_lines,
            "finalByteLimit": self.args.final_bytes,
            "truncationRisk": True,
            "limitations": "Bounded tails; rotation/deletion/outages may lose logs; overlap may duplicate lines.",
            "jobSnapshotAvailable": self.job is not None,
            "podsSnapshotAvailable": self.pods is not None,
            "expectedPods": self.expected_pods,
            "drivers": [dict(worker.status) for worker in self.workers.values()],
            "events": list(self.events),
        })

    def command(self, arguments, deadline=None):
        end = min(time.monotonic() + self.args.command_timeout,
                  self.deadline, deadline if deadline is not None else float("inf"))
        if time.monotonic() >= end or self.stop.is_set():
            return None
        process = subprocess.Popen(
            ["kubectl", *arguments, f"--request-timeout={self.args.request_timeout}s"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        try:
            while time.monotonic() < end and not self.stop.is_set():
                try:
                    output, error = process.communicate(timeout=min(0.1, max(0.001, end - time.monotonic())))
                    if process.returncode:
                        self.event(f"kubectl {' '.join(arguments)} exited {process.returncode}: "
                                   + error.decode(errors="replace")[-4096:])
                        return None
                    return output
                except subprocess.TimeoutExpired:
                    continue
            self.event(f"kubectl {' '.join(arguments)} exceeded wall-clock deadline or was cancelled")
            return None
        finally:
            kill_process(process)
            process.stdout.close()
            process.stderr.close()

    def snapshot(self, resource, deadline=None):
        arguments = ["get", resource, "--namespace", self.args.namespace, "-o", "json"]
        arguments += ["cl2"] if resource == "job" else ["-l", "job-name=cl2"]
        raw = self.command(arguments, deadline)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("expected an object")
            if resource == "pods" and not isinstance(value.get("items"), list):
                raise ValueError("missing items list")
            if resource == "job" and not isinstance(value.get("metadata"), dict):
                raise ValueError("missing Job metadata")
        except (ValueError, TypeError) as error:
            self.event(f"Invalid {resource} JSON: {error}")
            return None
        self.write_json(f"{resource}.json", value)
        return value

    def discover(self, pods):
        present = set()
        for pod in pods["items"]:
            metadata = pod.get("metadata", {})
            name, uid = metadata.get("name"), metadata.get("uid")
            containers = pod.get("spec", {}).get("containers", [])
            if not name or not uid or not containers:
                self.event("Pod snapshot missing name, UID or containers")
                continue
            statuses = {item["name"]: item for item in pod.get("status", {}).get("containerStatuses", [])}
            for container in containers:
                container_name = container["name"]
                key = (uid, container_name)
                present.add(key)
                state = statuses.get(container_name, {}).get("state", {})
                phase = pod.get("status", {}).get("phase")
                print(f"CL2 POD: {name} uid={uid} container={container_name} phase={phase} state={json.dumps(state)}",
                      flush=True)
                if key not in self.workers:
                    worker = Driver(self, name, uid, container_name)
                    self.workers[key] = worker
                    worker.status["state"] = state
                    if "terminated" in state or phase in ("Succeeded", "Failed"):
                        worker.finish.set()
                    worker.start()
                worker = self.workers[key]
                worker.status["state"] = state
                worker.status["phase"] = phase
                if "terminated" in state or phase in ("Succeeded", "Failed"):
                    worker.finish.set()
        for key, worker in self.workers.items():
            if key not in present and not worker.missing.is_set():
                worker.missing.set()
                worker.finish.set()
                worker.status["disappeared"] = True
                self.event(f"Pod disappeared: {worker.identity}; retained logs may be incomplete")

    def begin_shutdown(self):
        if self.deadline == float("inf"):
            self.shutdown_end = time.monotonic() + self.args.shutdown_grace
            # Reserve part of the one shared grace period for process/thread reaping.
            self.deadline = self.shutdown_end - min(1, self.args.shutdown_grace / 10)

    def signal(self, number, frame):
        if self.exit_code is None:
            self.exit_code = 128 + number
        self.begin_shutdown()
        self.stop.set()

    def run(self):
        # A fresh directory per build/stage/attempt prevents stale log identity reuse.
        self.directory.mkdir(parents=True, exist_ok=True)
        if any(self.directory.iterdir()):
            raise ValueError("log directory must be empty (use a unique stage/attempt directory)")
        self.write_json("job.json", None)
        self.write_json("pods.json", None)
        self.save_status()
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, self.signal)
        try:
            self.command(["create", "namespace", self.args.namespace])
            if self.command(["apply", "-f", self.args.manifest]) is None:
                self.exit_code = self.exit_code if self.exit_code is not None else 1
                return self.exit_code
            failed_since = None
            while not self.stop.is_set():
                cycle_start = time.monotonic()
                budget_end = failed_since + self.args.job_error_budget if failed_since is not None else None
                self.job = self.snapshot("job", budget_end)
                if self.job is None:
                    failed_since = cycle_start if failed_since is None else failed_since
                else:
                    failed_since = None
                    self.expected_pods = self.job.get("spec", {}).get("completions")
                    conditions = self.job.get("status", {}).get("conditions", [])
                    terminal = {item.get("type") for item in conditions if item.get("status") == "True"}
                    if "Failed" in terminal or "Complete" in terminal:
                        self.exit_code = 1 if "Failed" in terminal else 0
                        print(f"CL2 JOB: {json.dumps(conditions)}", flush=True)
                        self.begin_shutdown()
                budget_end = failed_since + self.args.job_error_budget if failed_since is not None else None
                self.pods = self.snapshot("pods", budget_end)
                if self.pods is not None:
                    self.discover(self.pods)
                self.save_status()
                if self.exit_code is not None:
                    break
                if failed_since is not None and time.monotonic() >= budget_end:
                    self.event("Continuous Job read failure budget exhausted")
                    self.exit_code = 1
                    break
                next_poll = cycle_start + self.args.poll_interval
                if budget_end is not None:
                    next_poll = min(next_poll, budget_end)
                self.stop.wait(max(0, next_poll - time.monotonic()))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            self.event(f"Monitor error: {error}")
            if self.exit_code is None:
                self.exit_code = 1
        finally:
            self.begin_shutdown()
            for worker in self.workers.values():
                worker.finish.set()
            for worker in self.workers.values():
                worker.join(max(0, self.deadline - time.monotonic()))
            # Each worker enforces this same deadline on pipes and final fetches.
            for worker in self.workers.values():
                if worker.is_alive():
                    self.event(f"Shutdown deadline reached: {worker.identity}")
                    worker.cancel()
            for worker in self.workers.values():
                worker.join(max(0, self.shutdown_end - time.monotonic()))
                if worker.is_alive():
                    self.event(f"Collector did not reap within grace: {worker.identity}")
                if worker.status["finalFetch"] != "ok":
                    self.event(f"Incomplete final collection: {worker.identity}")
            if not self.workers:
                self.event("No driver pods discovered; logs unavailable")
            elif self.expected_pods is not None and len({key[0] for key in self.workers}) < self.expected_pods:
                self.event(f"Discovered fewer pods than Job completions ({self.expected_pods})")
            if self.exit_code is None:
                self.exit_code = 1
            self.save_status(finished=True)
            if self.partial:
                print("##vso[task.logissue type=warning]CL2 log collection is partial; see collection-status.json",
                      flush=True)
        return self.exit_code


class Driver(threading.Thread):
    def __init__(self, collector, name, uid, container):
        super().__init__(daemon=True)
        self.collector = collector
        self.identity = f"{name}/{uid}/{container}"
        self.name_arg, self.container = name, container
        filename = f"{name}--{uid}--{container}.log"
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", filename):
            raise ValueError(f"Unsafe pod identity: {self.identity}")
        self.path = collector.directory / filename
        self.finish = threading.Event()
        self.missing = threading.Event()
        self.abort = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        self.status = {"pod": name, "uid": uid, "container": container, "file": filename,
                       "bytes": 0, "lastTimestamp": None, "finalFetch": "pending",
                       "streamAttempts": 0, "disappeared": False}
        self.pending = b""

    def cancel(self):
        with self.process_lock:
            self.abort.set()
            if self.process is not None:
                kill_process(self.process, wait=False)

    def persist(self, output, data):
        # Unbuffered writes make the cursor mean persisted-to-file, not queued in Python.
        view = memoryview(data)
        while view:
            written = output.write(view)
            if not written:
                raise OSError("short log write")
            self.status["bytes"] += written
            view = view[written:]
        self.pending += data
        lines = self.pending.split(b"\n")
        self.pending = lines.pop()
        for line in lines:
            token = line.split(b" ", 1)[0].decode("ascii", errors="replace")
            try:
                since_timestamp(token)
            except ValueError:
                continue
            self.status["lastTimestamp"] = token
        # A pathological unterminated line must not grow the cursor buffer forever.
        if len(self.pending) > 131072:
            self.pending = b""

    def fetch(self, output, follow):
        args = self.collector.args
        command = ["kubectl", "logs", self.name_arg, "--namespace", args.namespace,
                   "--container", self.container, "--timestamps",
                   f"--request-timeout={0 if follow else args.request_timeout}s"]
        if self.status["lastTimestamp"]:
            command += ["--since-time", since_timestamp(self.status["lastTimestamp"])]
        else:
            command += [f"--tail={args.tail_lines}"]
        if follow:
            command += ["--follow"]
        else:
            command += [f"--tail={args.tail_lines}", f"--limit-bytes={args.final_bytes}"]
        end = time.monotonic() + (args.stream_lifetime if follow else args.command_timeout)
        with self.process_lock:
            if self.abort.is_set() or time.monotonic() >= self.collector.deadline:
                return False
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
            self.process = process
        reason = "eof"
        errors = bytearray()
        received = 0
        self.pending = b""
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    remaining = min(end, self.collector.deadline) - time.monotonic()
                    if remaining <= 0 or self.abort.is_set():
                        reason = "lifetime/deadline"
                        break
                    if self.missing.is_set() or (follow and self.finish.is_set()):
                        reason = "stopping"
                        break
                    for key, _ in selector.select(min(0.05, remaining)):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                        elif key.data == "stderr":
                            errors.extend(data)
                            del errors[:-4096]
                        else:
                            if not follow:
                                data = data[:max(0, args.final_bytes - received)]
                            self.persist(output, data)
                            received += len(data)
                            if not follow and received >= args.final_bytes:
                                reason = "byte-limit"
                                break
                    if reason == "byte-limit":
                        break
            try:
                return_code = process.wait(timeout=max(0, min(0.1, end - time.monotonic(),
                                                              self.collector.deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                return_code = None
        finally:
            with self.process_lock:
                kill_process(process)
                self.process = None
                process.stdout.close()
                process.stderr.close()
        if errors:
            self.collector.event(f"{self.identity} kubectl logs stderr: {errors.decode(errors='replace')}")
        if reason != "stopping" and (reason != "eof" or return_code != 0):
            self.collector.event(f"{self.identity} {'live' if follow else 'final'} logs: "
                                 f"{reason}, exit={return_code}; not a driver failure")
        if not self.status["lastTimestamp"]:
            self.collector.event(f"{self.identity}: no persisted timestamp; capture not confirmed")
        if follow and self.pending:
            self.collector.event(f"{self.identity}: unterminated record at stream boundary; "
                                 "inserting newline without advancing cursor")
            self.pending = b""
            self.persist(output, b"\n")
        return reason == "eof" and return_code == 0 and self.status["lastTimestamp"] is not None

    def run(self):
        try:
            with self.path.open("ab", buffering=0) as output:
                failures = 0
                while not self.finish.is_set() and not self.missing.is_set():
                    before = self.status["bytes"]
                    started = time.monotonic()
                    self.status["streamAttempts"] += 1
                    self.fetch(output, follow=True)
                    if self.finish.is_set() or self.missing.is_set():
                        break
                    healthy = (self.status["bytes"] > before and
                               time.monotonic() - started >= min(self.collector.args.retry_base,
                                                                self.collector.args.stream_lifetime))
                    failures = 0 if healthy else min(failures + 1, 3)
                    delay = self.collector.args.retry_base * 2 ** max(0, failures - 1)
                    delay += random.uniform(0, delay * 0.1)
                    self.collector.event(f"{self.identity}: stream interrupted; reconnecting with overlap "
                                         f"after {delay:.3f}s")
                    self.finish.wait(delay)
                if not self.missing.is_set() and time.monotonic() < self.collector.deadline:
                    self.status["finalFetch"] = "ok" if self.fetch(output, follow=False) else "partial"
                else:
                    self.status["finalFetch"] = "unavailable"
                    self.collector.event(f"{self.identity}: final logs unavailable")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.status["finalFetch"] = "error"
            self.collector.event(f"{self.identity}: collector error: {error}")


def positive(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--log-directory", required=True)
    parser.add_argument("--poll-interval", type=positive, default=60)
    parser.add_argument("--request-timeout", type=positive, default=20)
    parser.add_argument("--command-timeout", type=positive, default=30)
    parser.add_argument("--job-error-budget", type=positive, default=600)
    parser.add_argument("--stream-lifetime", type=positive, default=600)
    parser.add_argument("--shutdown-grace", type=positive, default=60)
    parser.add_argument("--retry-base", type=positive, default=60)
    parser.add_argument("--tail-lines", type=int, default=2000)
    parser.add_argument("--final-bytes", type=int, default=4 * 1024 * 1024)
    args = parser.parse_args()
    if args.tail_lines <= 0 or args.final_bytes <= 0:
        parser.error("tail-lines and final-bytes must be positive")
    return Collector(args).run()


if __name__ == "__main__":
    sys.exit(main())
