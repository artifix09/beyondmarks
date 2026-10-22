"""Shared plumbing for the factory scripts.

Resumability lives here. Every stage writes a JSONL manifest as it goes and
skips work already recorded, so a disconnected Colab runtime, a rate limit or
a laptop lid costs you the page you were on and nothing else.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def env(name: str, *, required: bool = True, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(
            f"{name} is not set.\n"
            "  Locally: put it in factory/.env and load it with python-dotenv.\n"
            "  Colab:   add it in the secrets panel (key icon), never in a cell."
        )
    return value or ""


# --- manifests ----------------------------------------------------------


class Manifest:
    """An append-only JSONL log of finished work, keyed by one field.

    Append-only on purpose: a crash mid-write loses one line, not the file.
    """

    def __init__(self, path: Path, key: str = "page") -> None:
        self.path = path
        self.key = key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._done: dict[Any, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a torn final line from a killed run
                self._done[row.get(self.key)] = row

    def has(self, key_value: Any) -> bool:
        row = self._done.get(key_value)
        return bool(row) and row.get("status") == "ok"

    def get(self, key_value: Any) -> dict | None:
        return self._done.get(key_value)

    def rows(self) -> Iterator[dict]:
        yield from self._done.values()

    def record(self, row: dict) -> None:
        self._done[row.get(self.key)] = row
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self._done.values() if r.get("status") == "ok")

    @property
    def failed(self) -> list[dict]:
        return [r for r in self._done.values() if r.get("status") != "ok"]


# --- retries ------------------------------------------------------------


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 2.0,
    what: str = "call",
) -> T:
    """Exponential backoff with jitter.

    Rate limits are the normal failure here, not the exception: a few hundred
    pages through one API key will hit them. Jitter matters because the
    workers all back off at once otherwise and retry in lockstep.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - the SDK raises many types
            last = exc
            if attempt == attempts - 1:
                break
            delay = base_delay * (2**attempt) + random.uniform(0, 1)
            print(f"  {what} failed ({exc}); retrying in {delay:.1f}s", flush=True)
            time.sleep(delay)
    raise RuntimeError(f"{what} failed after {attempts} attempts: {last}") from last


# --- page map -----------------------------------------------------------


class PageMap:
    """Chapter boundaries and the PDF-index to printed-page offset.

    Built by hand from the contents page in about twenty minutes. Inferring it
    is a day of work, and getting it wrong means every citation the student
    sees points at the wrong page.
    """

    def __init__(self, rows: list[dict]) -> None:
        self.rows = sorted(rows, key=lambda r: r["pdf_start"])

    @classmethod
    def from_csv(cls, path: Path) -> PageMap:
        import csv

        # The generated map explains itself in leading # comments, which
        # DictReader would otherwise read as the header row.
        lines = [
            line
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        rows = []
        for raw in csv.DictReader(lines):
            if not raw.get("pdf_start"):
                continue
            if not (raw.get("printed_start") or "").strip():
                sys.exit(
                    f"{path}: chapter {raw.get('chapter_no')} has no "
                    "printed_start. Open the merged PDF at page "
                    f"{raw.get('pdf_start')} and type the page number printed "
                    "on it. Every citation in that chapter depends on it."
                )
            rows.append(
                {
                    "chapter_no": int(raw["chapter_no"]),
                    "title": (raw.get("title") or "").strip(),
                    "pdf_start": int(raw["pdf_start"]),
                    "pdf_end": int(raw["pdf_end"]),
                    "printed_start": int(raw["printed_start"]),
                }
            )
        if not rows:
            sys.exit(f"{path} has no usable rows")
        return cls(rows)

    def chapter_of(self, pdf_index: int) -> dict | None:
        for row in self.rows:
            if row["pdf_start"] <= pdf_index <= row["pdf_end"]:
                return row
        return None

    def printed_page(self, pdf_index: int) -> int | None:
        """The number the student sees, derived from the chapter's offset."""
        row = self.chapter_of(pdf_index)
        if row is None:
            return None
        return row["printed_start"] + (pdf_index - row["pdf_start"])

    def content_pages(self) -> list[int]:
        return [
            i
            for row in self.rows
            for i in range(row["pdf_start"], row["pdf_end"] + 1)
        ]


# --- database -----------------------------------------------------------


def connect():
    """Direct Postgres connection to Supabase.

    The connection string is in the Supabase dashboard under Project settings
    → Database. The factory uses the service role: it writes textbook_chunks,
    which the browser must never be able to read.
    """
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(env("SUPABASE_DB_URL"), row_factory=dict_row)
