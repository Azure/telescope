"""Pulls one pprof profile from a pod over its IP (no port-forward)."""

import requests

from vmagent_loadtest.pprof import PROFILE_KINDS

from .discovery import Candidate

MAX_PROFILE_BYTES = 32 * 1024 * 1024  # a runaway endpoint must not be able to exhaust collector memory


class Fetcher:
    def __init__(self):
        self._session = requests.Session()
        self._session.trust_env = False  # pod IPs must bypass any proxy env vars

    def fetch(self, cand: Candidate, kind: str, seconds: int) -> bytes:
        endpoint = PROFILE_KINDS[kind][0].format(seconds=seconds)
        headers = {}
        if cand.target.bearer_token_file:
            with open(cand.target.bearer_token_file, encoding="utf-8") as f:
                headers["Authorization"] = "Bearer " + f.read().strip()
        timeout = (5, (seconds + 30) if kind == "cpu" else 30)
        verify = not cand.target.insecure_skip_verify
        with self._session.get(cand.base_url + endpoint, headers=headers, timeout=timeout,
                               verify=verify, stream=True) as resp:
            resp.raise_for_status()
            buf = bytearray()
            for chunk in resp.iter_content(1 << 16):
                buf += chunk
                if len(buf) > MAX_PROFILE_BYTES:
                    raise ValueError(f"profile larger than {MAX_PROFILE_BYTES} bytes")
            return bytes(buf)
