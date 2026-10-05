"""Build synthetic pprof payloads (gzipped profile.proto) for tests."""

import gzip

from tests.vmagent_loadtest.test_profiling import _field, _varint


def build(sample_types: list[tuple[str, str]], stacks: list[tuple[list[str], list[int]]],
          duration_ns: int = 0, time_nanos: int = 1_700_000_000_000_000_000) -> bytes:
    """stacks: [(frames leaf-first, values aligned with sample_types)]"""
    strings = [""]

    def s(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    msg = b""
    for typ, unit in sample_types:
        msg += _field(1, 2, _field(1, 0, s(typ)) + _field(2, 0, s(unit)))
    frames: dict[str, int] = {}
    for frame_list, _ in stacks:
        for fr in frame_list:
            frames.setdefault(fr, len(frames) + 1)
    for fr, fid in frames.items():
        msg += _field(5, 2, _field(1, 0, fid) + _field(2, 0, s(fr)))
        msg += _field(4, 2, _field(1, 0, fid) + _field(4, 2, _field(1, 0, fid)))
    for frame_list, values in stacks:
        locs = _field(1, 2, b"".join(_varint(frames[f]) for f in frame_list))
        vals = _field(2, 2, b"".join(_varint(v) for v in values))
        msg += _field(2, 2, locs + vals)
    for text in strings:
        msg += _field(6, 2, text.encode())
    msg += _field(9, 0, time_nanos)
    if duration_ns:
        msg += _field(10, 0, duration_ns)
    return gzip.compress(msg)


MALLOC = "runtime.mallocgc"
GC_WORKER = ["runtime.scanobject", "runtime.gcDrain", "runtime.gcBgMarkWorker", "runtime.goexit"]
ZSTD = ["github.com/valyala/gozstd.compress", "pkg/rw.send", "main.main"]
SCRAPE = ["github.com/VictoriaMetrics/VictoriaMetrics/lib/promscrape.(*scrapeWork).run", "main.main"]


def cpu_profile(duration_s: int = 10) -> bytes:
    stacks = [(GC_WORKER, [10, 4_000]), (ZSTD, [5, 2_000]), (SCRAPE, [3, 1_000]), ([MALLOC, "main.main"], [2, 500])]
    return build([("samples", "count"), ("cpu", "nanoseconds")], stacks, duration_ns=duration_s * 1_000_000_000)


def heap_profile() -> bytes:
    return build([("inuse_objects", "count"), ("inuse_space", "bytes")],
                 [([MALLOC, "pkg/a.alloc", "main.main"], [1, 6_000]), (["pkg/b.alloc", "main.main"], [1, 2_000])])
