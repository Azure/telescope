"""Compact per-profile roll-ups for continuous collection.

A full-stack export is ~200 KB of Kusto rows per profile, too much to ship every
few minutes from every underlay. A roll-up keeps what the savings analysis
actually needs (~60 rows):

  total     one row: all samples in the profile
  category  stack-aware flat value per category (see categories.py), so the GC /
            zstd attribution that needs the whole stack survives the roll-up
  function  top functions by flat, plus top by cumulative (both columns filled)
  other     flat value not covered by the listed functions, so sums reconcile
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .categories import categorize_stack
from .pprof import PROFILE_KINDS, Profile, aggregate_stacks, parse_profile

OTHER_NAME = "(other)"
# Frames present in (almost) every stack (runtime.goexit, main.main, ...) carry no signal in a cum ranking.
ROOT_CUM_FRACTION = 0.995


@dataclass
class Rollup:
    sample_type: str
    unit: str
    duration_sec: float
    time_nanos: int
    total: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    functions: list[tuple[str, int, int]] = field(default_factory=list)  # (name, flat, cum)
    other_flat: int = 0


def _by_value(kv: tuple[str, int]) -> tuple[int, str]:
    """Rank by value descending; ties broken by name so the same profile always yields the same rows."""
    return -kv[1], kv[0]


def build_rollup(prof: Profile, sample_type: str, top_flat: int = 40, top_cum: int = 15,
                 duration_sec: float | None = None) -> Rollup:
    idx = prof.sample_type_index(sample_type)
    stacks, total = aggregate_stacks(prof, sample_type, top_k=10**9, max_depth=10**6)
    roll = Rollup(sample_type=sample_type, unit=prof.sample_types[idx][1],
                  duration_sec=prof.duration_nanos / 1e9 if duration_sec is None else duration_sec,
                  time_nanos=prof.time_nanos, total=total)
    flat: dict[str, int] = {}
    cum: dict[str, int] = {}
    for frames, value in stacks:
        cat = categorize_stack(frames)
        roll.categories[cat] = roll.categories.get(cat, 0) + value
        flat[frames[0]] = flat.get(frames[0], 0) + value
        for fn in dict.fromkeys(frames):  # each function once per stack, in stack order (a set would be hash-ordered)
            cum[fn] = cum.get(fn, 0) + value

    keep = {fn for fn, _ in sorted(flat.items(), key=_by_value)[:top_flat]}
    informative = ((fn, v) for fn, v in cum.items() if v < total * ROOT_CUM_FRACTION)
    keep |= {fn for fn, _ in sorted(informative, key=_by_value)[:top_cum]}
    roll.functions = sorted(((fn, flat.get(fn, 0), cum[fn]) for fn in keep),
                            key=lambda t: (-t[1], -t[2], t[0]))
    roll.other_flat = total - sum(f for _, f, _ in roll.functions)
    return roll


def _iso(nanos: int) -> str:
    seconds = nanos / 1e9 if nanos else datetime.now(timezone.utc).timestamp()
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def rollup_rows(ctx: dict, component: str, pod: str, container: str, image: str, kind: str,
                data: bytes, top_flat: int = 40, top_cum: int = 15) -> list[dict]:
    """Decode one pprof payload and return ProfileRollup rows (empty if the sample type is absent)."""
    prof = parse_profile(data)
    sample_type = PROFILE_KINDS[kind][1]
    try:
        # Only CPU profiles have a meaningful duration; heap/allocs/goroutine are instantaneous.
        roll = build_rollup(prof, sample_type, top_flat, top_cum,
                            duration_sec=None if kind == "cpu" else 0.0)
    except KeyError:
        return []
    base = {**ctx, "Timestamp": _iso(roll.time_nanos), "Component": component, "Pod": pod,
            "Container": container, "Image": image, "ProfileType": kind, "SampleType": sample_type,
            "Unit": roll.unit, "DurationSec": roll.duration_sec}
    rows = [{**base, "Kind": "total", "Name": "", "Flat": roll.total, "Cum": roll.total}]
    rows += [{**base, "Kind": "category", "Name": cat, "Flat": v, "Cum": v}
             for cat, v in sorted(roll.categories.items(), key=lambda kv: kv[1], reverse=True)]
    rows += [{**base, "Kind": "function", "Name": fn, "Flat": f, "Cum": c} for fn, f, c in roll.functions]
    if roll.other_flat > 0:
        rows.append({**base, "Kind": "other", "Name": OTHER_NAME, "Flat": roll.other_flat, "Cum": 0})
    return rows
