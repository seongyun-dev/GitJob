"""Cross-run identity for collected postings.

The per-site `Cursor` already skips postings inside one run, but it is keyed by
the run's date range and throws its ids away the moment the range moves:

    if raw["start_date"] != fresh.start_date or raw["end_date"] != fresh.end_date:
        return fresh            # "a different range says nothing about this run"

That is correct for *resume* — a half-finished run of 2026-09-10 must not be
resumed from 2026-09-09's page cursor — but it means a daily schedule, which
asks for a new range every day, starts every run with an empty id set. The
manifests show exactly that: `ids_known_before_run=0` on every first run of a
day, and 12.8% of all collected records are the same posting fetched again.

This store is the other half: identity that outlives the range. It answers one
question — have we seen this posting before, and has it changed — and nothing
else. It deliberately does not know about pages, ranges or resume.

Why `content_hash` rather than the record: a posting that is re-listed
unchanged should not be re-emitted, but one whose body changed must be, and the
only way to tell them apart is to compare a digest of the content. The hash
comes from `normalize.content_hash_for`, which excludes `collected_at` and the
run id precisely so the same posting hashes the same on every fetch.

`content_hash` is a change detector, never an identity: two different postings
that happen to hash alike are still two postings. Identity is
`source_site` + `source_posting_id` (`normalize.source_record_id_for`), and the
posting's URL is only a fallback for a site that ever stops giving us an id.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

__all__ = [
    "Decision",
    "PostingIdentityStore",
    "SeenPosting",
]


class Decision(str, Enum):
    """What a run should do with one listed posting."""

    #: First time this id has ever been seen. Emit it.
    NEW = "NEW"
    #: Seen before, same content hash. Do not emit; do not republish.
    UNCHANGED = "UNCHANGED"
    #: Seen before, content hash moved. Emit it as an update.
    CHANGED = "CHANGED"


@dataclass
class SeenPosting:
    content_hash: str
    first_seen_at: str
    last_seen_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "content_hash": self.content_hash,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
        }


def _atomic_write(path: Path, text: str) -> None:
    """Write via a sibling temp file then rename.

    A run that dies midway through writing the store would otherwise leave
    truncated JSON, and the next run would read it as "nothing seen" and
    re-collect everything — the same silent-reset this module exists to stop.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


@dataclass
class PostingIdentityStore:
    """`source_posting_id` -> what we last saw for it, for one site.

    Held in memory for the run and persisted once, by the caller, after the
    batch is safely written. Persisting earlier repeats S15P21E102-174: the
    store would claim postings whose batch never landed, and the next run would
    skip them forever.
    """

    source_site: str
    path: Path | None = None
    seen: dict[str, SeenPosting] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.seen is None:
            self.seen = {}

    # -- loading ---------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None, *, source_site: str) -> PostingIdentityStore:
        """Read the store, or start empty when it is absent or unreadable.

        Unreadable is treated as empty rather than fatal: a corrupt store costs
        one run of duplicates, while refusing to start costs the whole run, and
        the postings a run drops cannot be fetched again once they close.
        """

        store = cls(source_site=source_site, path=path)
        if path is None or not path.exists():
            return store
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return store
        entries = raw.get("postings") if isinstance(raw, dict) else None
        if not isinstance(entries, dict):
            return store
        for posting_id, value in entries.items():
            if not isinstance(value, dict):
                continue
            content_hash = value.get("content_hash")
            first_seen = value.get("first_seen_at")
            last_seen = value.get("last_seen_at")
            if not isinstance(content_hash, str) or not content_hash:
                continue
            store.seen[str(posting_id)] = SeenPosting(
                content_hash=content_hash,
                first_seen_at=str(first_seen or ""),
                last_seen_at=str(last_seen or first_seen or ""),
            )
        return store

    # -- decisions -------------------------------------------------------

    def decide(self, posting_id: str, content_hash: str) -> Decision:
        """Classify one posting. Does not mutate; call `record` to commit."""

        previous = self.seen.get(posting_id)
        if previous is None:
            return Decision.NEW
        if previous.content_hash == content_hash:
            return Decision.UNCHANGED
        return Decision.CHANGED

    def record(
        self,
        posting_id: str,
        content_hash: str,
        *,
        now: datetime | None = None,
    ) -> Decision:
        """Classify and remember one posting.

        `first_seen_at` is written once and never moved; `last_seen_at` advances
        on every sighting, including an UNCHANGED one — a posting still being
        listed is information even when its body has not moved.
        """

        stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        decision = self.decide(posting_id, content_hash)
        previous = self.seen.get(posting_id)
        if previous is None:
            self.seen[posting_id] = SeenPosting(
                content_hash=content_hash,
                first_seen_at=stamp,
                last_seen_at=stamp,
            )
        else:
            previous.content_hash = content_hash
            previous.last_seen_at = stamp
        return decision

    def first_seen_at(self, posting_id: str) -> str | None:
        entry = self.seen.get(posting_id)
        return entry.first_seen_at if entry else None

    def last_seen_at(self, posting_id: str) -> str | None:
        entry = self.seen.get(posting_id)
        return entry.last_seen_at if entry else None

    # -- persistence -----------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        if target is None:
            return
        payload = {
            "schema_version": "posting-identity/v1",
            "source_site": self.source_site,
            "updated_at": datetime.now(UTC).isoformat(),
            "postings": {
                posting_id: entry.as_dict()
                for posting_id, entry in sorted(self.seen.items())
            },
        }
        _atomic_write(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def __len__(self) -> int:
        return len(self.seen)


def identity_path_for(cursor_path: Path | None) -> Path | None:
    """Put the store beside the cursor it complements.

    Deriving it rather than adding a second CLI flag keeps the schedule entries
    unchanged: every run already passes `--cursor ../data/<site>/cursor.json`,
    so the store lands at `../data/<site>/identity.json` with no new wiring.
    """

    if cursor_path is None:
        return None
    return cursor_path.with_name("identity.json")
