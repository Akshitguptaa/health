"""Run summary printed at the end of every scrape or ingest."""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class RunStats:
    pages_processed: int = 0
    pages_skipped: int = 0        # already done in an earlier run
    pages_fetched: int = 0        # live HTTP fetches only
    retries: int = 0
    facilities_seen: int = 0
    facilities_loaded: int = 0    # unique, valid
    duplicates_merged: int = 0
    rejected: Counter = field(default_factory=Counter)
    started: float = field(default_factory=time.monotonic)
    duration_s: float = 0.0

    def finish(self) -> "RunStats":
        self.duration_s = round(time.monotonic() - self.started, 2)
        return self

    def as_dict(self) -> dict:
        return {
            "pages_processed": self.pages_processed,
            "pages_skipped": self.pages_skipped,
            "pages_fetched": self.pages_fetched,
            "retries": self.retries,
            "facilities_seen": self.facilities_seen,
            "facilities_loaded": self.facilities_loaded,
            "duplicates_merged": self.duplicates_merged,
            "rejected_total": sum(self.rejected.values()),
            "rejected_by_reason": dict(self.rejected),
            "duration_s": self.duration_s,
        }

    def format(self) -> str:
        d = self.as_dict()
        lines = [
            "---- run report ----",
            f"pages processed : {d['pages_processed']} (skipped as already done: {d['pages_skipped']})",
            f"pages fetched   : {d['pages_fetched']}  retries: {d['retries']}",
            f"facilities seen : {d['facilities_seen']}",
            f"loaded (unique) : {d['facilities_loaded']}  duplicates merged: {d['duplicates_merged']}",
            f"rejected        : {d['rejected_total']}",
        ]
        for reason, n in sorted(self.rejected.items()):
            lines.append(f"    {reason}: {n}")
        lines.append(f"duration        : {d['duration_s']}s")
        return "\n".join(lines)
