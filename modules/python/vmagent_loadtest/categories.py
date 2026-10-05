"""Single source of truth for classifying profile frames into savings categories.

Used in two places that must agree:
  * the continuous collector (underlay_profiler) classifies stacks client-side
    so it can ship compact roll-ups instead of every stack;
  * profile_schema.py renders these same rules into the Kusto functions
    ProfileCategory / ProfileStackCategory used on full-stack lab data.

Regexes are partial-match (Python re.search == Kusto `matches regex`) and are
limited to the RE2-compatible subset so they behave the same in both engines.
"""

import re

OTHER = "other"

# Evaluated top to bottom on the *leaf* function; first match wins.
LEAF_RULES: list[tuple[str, str]] = [
    (r"^(runtime\.(futex|epollwait|usleep|osyield|procyield|nanotime|notesleep|notetsleep|findRunnable|schedule|stealWork|park_m|mcall|gopark|goready|wakep|netpoll|lock2|unlock2)|internal/runtime/atomic)",
     "scheduler-and-idle"),
    (r"^(syscall\.|internal/runtime/syscall|internal/poll\.|runtime\.(cgocall|entersyscall|exitsyscall)|os\.\(\*File\)|net\.\(\*(netFD|conn|TCPConn)\))",
     "syscall-and-network-io"),
    (r"^runtime\.", "gc-and-allocation"),
    (r"(compress/(flate|gzip|zlib)|klauspost/compress|valyala/gozstd|golang/snappy|/zstd|/snappy)", "compression"),
    (r"^(crypto/|vendor/golang\.org/x/crypto|golang\.org/x/crypto)", "tls-and-crypto"),
    (r"(google\.golang\.org/grpc|golang\.org/x/net/http2|net/http\.\(\*http2|net/http\.\(\*(conn|persistConn))",
     "grpc-and-http2"),
    (r"(lib/(protoparser|promscrape|prompb|prompbmarshal|promrelabel|promutils|promutil|bytesutil|storage|mergeset|netutil|streamaggr|persistentqueue|encoding|fasttime)|VictoriaMetrics/(app|fastcache|easyproto|metricsql))",
     "metrics-pipeline"),
    (r"(lib/logger|k8s\.io/klog|go\.uber\.org/zap|^log\.|^log/slog)", "logging"),
    (r"^(encoding/json|reflect\.|fmt\.|strconv\.|strings\.|sort\.|regexp\.|bytes\.|sync/atomic|internal/bytealg|internal/runtime/maps|indexbytebody|memeqbody|cmpbody|countbody)",
     "stdlib-misc"),
]

# Evaluated first, on the whole stack, because the leaf alone hides the cause:
# GC worker/assist internals look like generic runtime frames, and cgo zstd
# shows up as a syscall leaf. ("frame", X): some frame == X; ("contains", X):
# the stack text contains X.
STACK_RULES: list[tuple[str, str, str]] = [
    ("frame", "runtime.gcBgMarkWorker", "gc-and-allocation"),
    ("frame", "runtime.gcAssistAlloc", "gc-and-allocation"),
    ("contains", "gozstd.", "compression"),
]

_LEAF_RE = [(re.compile(rx), cat) for rx, cat in LEAF_RULES]


def categorize_leaf(fn: str) -> str:
    for rx, cat in _LEAF_RE:
        if rx.search(fn):
            return cat
    return OTHER


def categorize_stack(frames: tuple[str, ...] | list[str]) -> str:
    """Category for a stack whose frames are leaf-first."""
    text = None
    for kind, needle, cat in STACK_RULES:
        if kind == "frame":
            if needle in frames:
                return cat
        else:
            if text is None:
                text = "\n".join(frames)
            if needle in text:
                return cat
    return categorize_leaf(frames[0]) if frames else OTHER


def kql_category_function() -> str:
    lines = [f'        fn matches regex @"{rx}", "{cat}",' for rx, cat in LEAF_RULES]
    return (
        ".create-or-alter function with (docstring='Classify a Go function into a savings category', folder='Profiling')\n"
        "ProfileCategory(fn: string) {\n    case(\n" + "\n".join(lines) + f'\n        "{OTHER}")\n' + "}\n"
    )


def kql_stack_category_function() -> str:
    lines = []
    for kind, needle, cat in STACK_RULES:
        cond = (f'array_index_of(stack, "{needle}") >= 0' if kind == "frame"
                else f'tostring(stack) contains "{needle}"')
        lines.append(f'        {cond}, "{cat}",')
    return (
        ".create-or-alter function with (docstring='Stack-aware category: GC worker/assist and cgo zstd stacks are classified regardless of leaf', folder='Profiling')\n"
        "ProfileStackCategory(stack: dynamic, leaf: string) {\n    case(\n" + "\n".join(lines)
        + "\n        ProfileCategory(leaf))\n}\n"
    )
