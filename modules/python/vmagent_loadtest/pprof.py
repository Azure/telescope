"""Dependency-free decoder for pprof (profile.proto) payloads.

Go's net/http/pprof endpoints return a gzipped protobuf `Profile`. This module
decodes just the fields needed to attribute CPU/memory to call stacks, so the
load test (and later a prod collector) can flatten profiles into Kusto rows
without needing `go tool pprof` or generated protobuf classes.

Schema reference: https://github.com/google/pprof/blob/main/proto/profile.proto
"""

import gzip
from dataclasses import dataclass, field

OTHER_FRAME = "(other)"

# collection kind -> (endpoint, sample type kept). heap/allocs each carry four
# sample types; keep one per kind so rows are not duplicated.
PROFILE_KINDS = {
    "cpu": ("/debug/pprof/profile?seconds={seconds}", "cpu"),
    "heap": ("/debug/pprof/heap", "inuse_space"),
    "allocs": ("/debug/pprof/allocs", "alloc_space"),
    "goroutine": ("/debug/pprof/goroutine?debug=0", "goroutine"),
}


@dataclass
class Profile:
    sample_types: list[tuple[str, str]] = field(default_factory=list)  # (type, unit)
    # (location ids leaf-first, values aligned with sample_types)
    samples: list[tuple[list[int], list[int]]] = field(default_factory=list)
    # location id -> function names, innermost (inlined) frame first
    locations: dict[int, list[str]] = field(default_factory=dict)
    time_nanos: int = 0
    duration_nanos: int = 0
    period: int = 0
    period_type: tuple[str, str] = ("", "")

    def sample_type_index(self, name: str) -> int:
        for i, (typ, _unit) in enumerate(self.sample_types):
            if typ == name:
                return i
        raise KeyError(f"sample type {name!r} not in {self.sample_types}")


def _varint(buf, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _fields(buf):
    """Yield (field_number, wire_type, value) for every field in a message."""
    pos = 0
    end = len(buf)
    while pos < end:
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 2:
            length, pos = _varint(buf, pos)
            value = buf[pos:pos + length]
            pos += length
        elif wire == 1:
            value = buf[pos:pos + 8]
            pos += 8
        elif wire == 5:
            value = buf[pos:pos + 4]
            pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield number, wire, value


def _int64(value: int) -> int:
    return value - (1 << 64) if value >= (1 << 63) else value


def _repeated_varints(wire: int, value) -> list[int]:
    """Repeated scalar fields may be packed (wire 2) or one varint per tag (wire 0)."""
    if wire == 0:
        return [value]
    out = []
    pos = 0
    while pos < len(value):
        item, pos = _varint(value, pos)
        out.append(item)
    return out


def _value_type(msg) -> tuple[int, int]:
    """ValueType: (type, unit) string-table indexes."""
    typ = unit = 0
    for n, _w, v in _fields(msg):
        if n == 1:
            typ = v
        elif n == 2:
            unit = v
    return typ, unit


def _sample(msg) -> tuple[list[int], list[int]]:
    locs: list[int] = []
    vals: list[int] = []
    for n, w, v in _fields(msg):
        if n == 1:
            locs.extend(_repeated_varints(w, v))
        elif n == 2:
            vals.extend(_int64(x) for x in _repeated_varints(w, v))
    return locs, vals


def _location(msg) -> tuple[int, list[int]]:
    """Location: (id, function ids of its lines, innermost inlined frame first)."""
    loc_id = 0
    funcs: list[int] = []
    for n, _w, v in _fields(msg):
        if n == 1:
            loc_id = v
        elif n == 4:  # line
            funcs.extend(lv for ln, _lw, lv in _fields(v) if ln == 1)
    return loc_id, funcs


def _function(msg) -> tuple[int, int]:
    """Function: (id, name string-table index)."""
    func_id = name = 0
    for n, _w, v in _fields(msg):
        if n == 1:
            func_id = v
        elif n == 2:
            name = v
    return func_id, name


def parse_profile(data: bytes) -> Profile:
    """Decode a (optionally gzipped) pprof profile."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)

    strings: list[str] = []
    raw_sample_types: list[tuple[int, int]] = []
    raw_locations: dict[int, list[int]] = {}
    raw_functions: dict[int, int] = {}
    prof = Profile()
    period_type_raw = (0, 0)

    for number, _wire, value in _fields(memoryview(data)):
        if number == 6:  # string_table
            strings.append(bytes(value).decode("utf-8", errors="replace"))
        elif number == 1:  # sample_type
            raw_sample_types.append(_value_type(value))
        elif number == 2:  # sample
            prof.samples.append(_sample(value))
        elif number == 4:  # location
            loc_id, funcs = _location(value)
            raw_locations[loc_id] = funcs
        elif number == 5:  # function
            func_id, name = _function(value)
            raw_functions[func_id] = name
        elif number == 9:
            prof.time_nanos = _int64(value)
        elif number == 10:
            prof.duration_nanos = _int64(value)
        elif number == 11:  # period_type
            period_type_raw = _value_type(value)
        elif number == 12:
            prof.period = _int64(value)

    def s(idx: int) -> str:
        return strings[idx] if 0 <= idx < len(strings) else ""

    prof.sample_types = [(s(t), s(u)) for t, u in raw_sample_types]
    prof.period_type = (s(period_type_raw[0]), s(period_type_raw[1]))
    prof.locations = {
        loc_id: [s(raw_functions.get(f, 0)) for f in funcs]
        for loc_id, funcs in raw_locations.items()
    }
    return prof


def aggregate_stacks(prof: Profile, sample_type: str, top_k: int = 2000,
                     max_depth: int = 64) -> tuple[list[tuple[tuple[str, ...], int]], int]:
    """Collapse samples into unique stacks for one sample type.

    Returns (stacks, total) where stacks is [(frames leaf-first, value)] sorted by
    descending value. Only the top_k stacks are kept individually; the rest are
    folded into a single (other) stack so the row count per profile is bounded
    while the total still reconciles with the profile.
    """
    idx = prof.sample_type_index(sample_type)
    merged: dict[tuple[str, ...], int] = {}
    total = 0
    for loc_ids, values in prof.samples:
        if idx >= len(values):
            continue
        value = values[idx]
        if value == 0:
            continue
        frames: list[str] = []
        for loc_id in loc_ids:
            frames.extend(prof.locations.get(loc_id, ()))
        stack = tuple(frames[:max_depth]) or (OTHER_FRAME,)
        merged[stack] = merged.get(stack, 0) + value
        total += value

    ordered = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
    if len(ordered) > top_k:
        rest = sum(v for _, v in ordered[top_k:])
        ordered = ordered[:top_k] + [((OTHER_FRAME,), rest)]
    return ordered, total


def split_go_func(name: str) -> tuple[str, str]:
    """Split 'github.com/x/y.(*T).m' into ('github.com/x/y', '(*T).m')."""
    slash = name.rfind("/")
    dot = name.find(".", slash + 1)
    if dot < 0:
        return "", name
    return name[:dot], name[dot + 1:]
