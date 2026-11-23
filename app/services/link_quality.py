import time
from dataclasses import dataclass
from typing import Literal

LinkState = Literal["ONLINE", "DEGRADED", "OFFLINE"]
HEARTBEAT_SECONDS = 1.0
OFFLINE_SECONDS = 2.5
DEGRADED_SECONDS = 1.5


@dataclass
class LinkQuality:
    last_heartbeat: float
    state: LinkState = "ONLINE"
    rtt_ms: float | None = None
    jitter_ms: float = 0
    previous_rtt_ms: float | None = None
    good_samples: int = 0
    bad_samples: int = 0
    sequence_gaps: int = 0
    received_frames: int = 0

    def heartbeat(self, now: float) -> None:
        self.last_heartbeat = now

    def observe_rtt(self, value_ms: float) -> None:
        if self.previous_rtt_ms is not None:
            self.jitter_ms += 0.125 * (
                abs(value_ms - self.previous_rtt_ms) - self.jitter_ms
            )
        self.previous_rtt_ms = value_ms
        self.rtt_ms = (
            value_ms
            if self.rtt_ms is None
            else self.rtt_ms + 0.2 * (value_ms - self.rtt_ms)
        )
        bad = self.rtt_ms > 500 or self.jitter_ms > 150
        self.bad_samples = self.bad_samples + 1 if bad else 0
        self.good_samples = 0 if bad else self.good_samples + 1

    def update(self, connected: bool, now: float | None = None) -> LinkState:
        age = (time.monotonic() if now is None else now) - self.last_heartbeat
        if not connected or age >= OFFLINE_SECONDS:
            self.state = "OFFLINE"
        elif age >= DEGRADED_SECONDS or self.bad_samples >= 3:
            self.state = "DEGRADED"
            self.good_samples = 0
        elif self.good_samples >= 3:
            self.state = "ONLINE"
        return self.state

    @property
    def observed_gap_ratio(self) -> float:
        total = self.received_frames + self.sequence_gaps
        return self.sequence_gaps / total if total else 0
