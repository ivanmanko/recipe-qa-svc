"""Per-IP sliding-window rate limiting (SPEC §7.15).

Written in-process rather than pulled in as a dependency: the service is a
single stateless instance, so any in-memory limiter — ours or a library's —
is per-instance anyway, and 40 owned lines are fully unit-testable without a
network or a clock. The limitation is declared in SPEC and README rather than
papered over: several replicas multiply the effective limit, and a
distributed source is not covered at all.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client: str) -> Decision:
        """Records the call when it is allowed. A rejected call is *not*
        recorded — otherwise a client that keeps retrying would keep pushing
        its own window forward and never recover."""
        if self._limit <= 0:
            return Decision(allowed=True)

        now = self._clock()
        cutoff = now - self._window
        self._evict(cutoff)

        hits = self._hits[client]
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) < self._limit:
            hits.append(now)
            return Decision(allowed=True)

        retry_after = max(1, int(hits[0] + self._window - now))
        return Decision(allowed=False, retry_after=retry_after)

    def tracked_clients(self) -> int:
        self._evict(self._clock() - self._window)
        return len(self._hits)

    def _evict(self, cutoff: float) -> None:
        """Drops clients with no calls left in the window, so the map does not
        grow without bound on a public endpoint."""
        stale = [
            client
            for client, hits in self._hits.items()
            if not hits or hits[-1] <= cutoff
        ]
        for client in stale:
            del self._hits[client]
