"""Stage 7 — prove the ingestion is good before anything is built on it.

Five gates, in order. Each one is cheap and fails loudly, and each is useless
until the one before it passes.

  C  coverage      every mapped page produced text
  D  chunk hygiene sizes, page ranges, nothing split that should not be
  E  integrity     768 dimensions, no empty vectors, model recorded
  F  self-retrieval a chunk's own sentence finds that chunk at rank 1
  G  gold set      known questions find the right page in the top 3

Gate F is the one that matters most and gets skipped most. It separates "the
pipeline is broken" from "retrieval is mediocre" — a dimension mismatch, a
missing normalisation or the wrong task type all show up here as a flat
failure, while chunking problems show up in Gate G as a middling score. The
two have completely different fixes, and without F you cannot tell them apart.

Usage:
    python -I validate_ingestion.py --book-id <uuid>
    python -I validate_ingestion.py --book-id <uuid> --gold gold_set.csv
"""

from __future__ import annotations

import argparse
import sys
import csv
import random
import re
import statistics as stats
from pathlib import Path

# Running with -I (isolated) drops the script's own directory from sys.path,
# so the sibling imports below need it put back explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import Manifest, PageMap, connect, env, with_retry

EMBED_DIM = 768
PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results: list[tuple[str, str, str]] = []


def record(gate: str, status: str, message: str) -> None:
    results.append((gate, status, message))
    mark = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " warn "}[status]
    print(f"[{mark}] {gate}: {message}")


# --- Gate C -------------------------------------------------------------


def gate_c(transcripts: Path, page_map: PageMap) -> None:
    print("\nGate C - coverage")
    manifest = Manifest(transcripts / "manifest.jsonl", key="pdf_index")
    expected = set(page_map.content_pages())
    got = {r["pdf_index"] for r in manifest.rows() if r.get("status") == "ok"}

    missing = sorted(expected - got)
    record(
        "C1 every mapped page transcribed",
        PASS if not missing else FAIL,
        f"{len(got)}/{len(expected)} pages"
        + (f", missing {missing[:15]}" if missing else ""),
    )

    thin = [
        r["pdf_index"]
        for r in manifest.rows()
        if r.get("status") == "ok"
        and r.get("page_kind") == "content"
        and (r.get("chars") or 0) < 200
    ]
    record(
        "C2 no silently empty content pages",
        PASS if not thin else WARN,
        f"{len(thin)} content pages under 200 chars"
        + (f": {thin[:15]}" if thin else ""),
    )

    low = [
        r["pdf_index"]
        for r in manifest.rows()
        if r.get("status") == "ok" and r.get("confidence") == "low"
    ]
    record(
        "C3 model confidence",
        PASS if len(low) <= len(expected) * 0.05 else WARN,
        f"{len(low)} pages marked low confidence"
        + (f": {low[:15]}" if low else ""),
    )


# --- Gate D -------------------------------------------------------------


def gate_d(conn, book_id: str) -> None:
    print("\nGate D - chunk hygiene")
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, heading, content, page_start, page_end
            from textbook_chunks where book_id = %s
            """,
            (book_id,),
        )
        rows = cur.fetchall()

    if not rows:
        record("D0 chunks exist", FAIL, "no chunks for this book")
        return

    words = [len(r["content"].split()) for r in rows]
    record(
        "D1 chunk count",
        PASS,
        f"{len(rows)} chunks, {min(words)}-{max(words)} words "
        f"(median {int(stats.median(words))})",
    )

    oversize = [w for w in words if w > 700]
    undersize = [w for w in words if w < 60]
    record(
        "D2 sizes in range",
        PASS if not oversize and not undersize else WARN,
        f"{len(oversize)} over 700 words, {len(undersize)} under 60",
    )

    no_pages = [r["id"] for r in rows if r["page_start"] is None]
    record(
        "D3 every chunk cites a page",
        PASS if not no_pages else FAIL,
        f"{len(no_pages)} chunks with no page_start",
    )

    bad_range = [
        r["id"]
        for r in rows
        if r["page_start"] is not None
        and r["page_end"] is not None
        and (r["page_end"] < r["page_start"] or r["page_end"] - r["page_start"] > 4)
    ]
    record(
        "D4 page ranges sane",
        PASS if not bad_range else FAIL,
        f"{len(bad_range)} chunks with a reversed or over-wide page range",
    )

    unbalanced = [
        r["id"] for r in rows if r["content"].count("$$") % 2 != 0
    ]
    record(
        "D5 no formula split across chunks",
        PASS if not unbalanced else FAIL,
        f"{len(unbalanced)} chunks with an odd number of $$ delimiters",
    )

    headless = [r["id"] for r in rows if not r["heading"]]
    record(
        "D6 chunks carry a heading",
        PASS if len(headless) < len(rows) * 0.1 else WARN,
        f"{len(headless)} chunks with no heading",
    )


# --- Gate E -------------------------------------------------------------


def gate_e(conn, book_id: str) -> None:
    print("\nGate E - embedding integrity")
    with conn.cursor() as cur:
        cur.execute(
            """
            select
                count(*)                                        as total,
                count(embedding)                                as with_vector,
                count(*) filter (where embedding_model is null) as no_model,
                count(distinct embedding_model)                 as models
            from textbook_chunks where book_id = %s
            """,
            (book_id,),
        )
        row = cur.fetchone()

        cur.execute(
            """
            select vector_dims(embedding) as dims, count(*) as n
            from textbook_chunks
            where book_id = %s and embedding is not null
            group by 1
            """,
            (book_id,),
        )
        dims = cur.fetchall()

        # An all-zero vector has no direction, so cosine distance against it is
        # undefined and it silently matches nothing. l2_norm arrived in
        # pgvector 0.7; on an older one the check is skipped rather than
        # failing the whole run.
        zeros: int | None
        try:
            cur.execute(
                """
                select count(*) as n from textbook_chunks
                where book_id = %s and embedding is not null
                  and l2_norm(embedding) = 0
                """,
                (book_id,),
            )
            zeros = cur.fetchone()["n"]
        except Exception:  # noqa: BLE001 - undefined_function on old pgvector
            conn.rollback()
            zeros = None

    record(
        "E1 every chunk embedded",
        PASS if row["total"] == row["with_vector"] else FAIL,
        f"{row['with_vector']}/{row['total']} chunks have a vector",
    )
    record(
        "E2 dimensions",
        PASS if dims == [{"dims": EMBED_DIM, "n": row["with_vector"]}] else FAIL,
        f"{dims}",
    )
    if zeros is None:
        record("E3 no zero vectors", WARN, "l2_norm unavailable (pgvector < 0.7), skipped")
    else:
        record(
            "E3 no zero vectors",
            PASS if zeros == 0 else FAIL,
            f"{zeros} all-zero embeddings",
        )
    record(
        "E4 model recorded, and only one",
        PASS if row["no_model"] == 0 and row["models"] == 1 else FAIL,
        f"{row['no_model']} rows without a model, {row['models']} distinct models",
    )


# --- retrieval ----------------------------------------------------------


def embed_query(client, model: str, text: str) -> list[float]:
    """Queries use RETRIEVAL_QUERY — a different vector from the same model."""
    from google.genai import types
    import math

    def call():
        return client.models.embed_content(
            model=model,
            contents=[text],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY", output_dimensionality=EMBED_DIM
            ),
        )

    vector = list(with_retry(call, what="embed query").embeddings[0].values)
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def search(conn, book_id: str, vector: list[float], k: int = 3) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, heading, page_start, page_end,
                   1 - (embedding <=> %s::vector) as score
            from textbook_chunks
            where book_id = %s and embedding is not null
            order by embedding <=> %s::vector
            limit %s
            """,
            (str(vector), book_id, str(vector), k),
        )
        return cur.fetchall()


def gate_f(conn, client, embed_model: str, book_id: str, sample: int) -> None:
    print("\nGate F - self-retrieval")
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, content from textbook_chunks
            where book_id = %s and embedding is not null
            """,
            (book_id,),
        )
        rows = cur.fetchall()

    if not rows:
        record("F1 self-retrieval", FAIL, "nothing to test")
        return

    random.seed(1234)  # same sample every run, so the number is comparable
    picked = random.sample(rows, min(sample, len(rows)))

    hits = 0
    misses: list[str] = []
    for chunk in picked:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", chunk["content"]) if len(s.split()) > 6]
        if not sentences:
            continue
        query = sentences[0]
        top = search(conn, book_id, embed_query(client, embed_model, query), k=1)
        if top and top[0]["id"] == chunk["id"]:
            hits += 1
        else:
            misses.append(query[:70])

    rate = hits / len(picked) if picked else 0
    record(
        "F1 a chunk's own sentence returns that chunk",
        PASS if rate >= 0.9 else FAIL,
        f"{hits}/{len(picked)} at rank 1 ({rate:.0%})",
    )
    if rate < 0.9:
        print("  This is a pipeline bug, not a quality problem. Check, in order:")
        print("    - documents embedded with RETRIEVAL_DOCUMENT, queries with RETRIEVAL_QUERY")
        print("    - vectors re-normalised after truncation to 768")
        print("    - the index is vector_cosine_ops and the query uses <=>")
        for miss in misses[:3]:
            print(f"    missed: {miss!r}")


def gate_g(conn, client, embed_model: str, book_id: str, gold_path: Path) -> None:
    print("\nGate G - gold set")
    if not gold_path.exists():
        record("G1 gold set", WARN, f"{gold_path} not found, skipped")
        print("  Build it: one row per question with the page its answer is on.")
        print("  Fifty rows is an hour's work and it is the acceptance test for")
        print("  every chunking change you make from here on.")
        return

    # Leading # comments explain the file; DictReader would read the first one
    # as the header.
    lines = [
        line
        for line in gold_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    gold = [r for r in csv.DictReader(lines) if r.get("question")]

    answerable = [r for r in gold if (r.get("page") or "").strip()]
    unanswerable = [r for r in gold if not (r.get("page") or "").strip()]

    hits = 0
    failures: list[str] = []
    for row in answerable:
        want = int(row["page"])
        top = search(conn, book_id, embed_query(client, embed_model, row["question"]), k=3)
        if any(
            r["page_start"] is not None
            and r["page_start"] - 1 <= want <= (r["page_end"] or r["page_start"]) + 1
            for r in top
        ):
            hits += 1
        else:
            got = [f"p{r['page_start']}-{r['page_end']}" for r in top]
            failures.append(f"{row['question'][:60]!r} wanted p{want}, got {got}")

    rate = hits / len(answerable) if answerable else 0
    status = PASS if rate >= 0.85 else (WARN if rate >= 0.70 else FAIL)
    record(
        "G1 recall@3 on known pages",
        status,
        f"{hits}/{len(answerable)} ({rate:.0%}) - target 85%, below 70% means fix chunking",
    )
    for failure in failures[:8]:
        print(f"    {failure}")

    if unanswerable:
        scores = []
        for row in unanswerable:
            top = search(conn, book_id, embed_query(client, embed_model, row["question"]), k=1)
            if top:
                scores.append(top[0]["score"])
        if scores:
            record(
                "G2 off-book questions score lower",
                PASS if max(scores) < 0.80 else WARN,
                f"best score on {len(scores)} off-book questions: {max(scores):.2f}"
                " — the chat threshold goes just above this",
            )


# --- main ---------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-id", required=True)
    ap.add_argument("--page-map", type=Path, default=Path("page_map.csv"))
    ap.add_argument("--transcripts", type=Path, default=Path("./work/transcripts"))
    ap.add_argument("--gold", type=Path, default=Path("gold_set.csv"))
    ap.add_argument("--sample", type=int, default=20, help="chunks for Gate F")
    ap.add_argument("--skip-retrieval", action="store_true", help="gates C-E only, no API calls")
    args = ap.parse_args()

    if args.page_map.exists():
        gate_c(args.transcripts, PageMap.from_csv(args.page_map))
    else:
        record("C0 page map", WARN, f"{args.page_map} not found, coverage skipped")

    with connect() as conn:
        gate_d(conn, args.book_id)
        gate_e(conn, args.book_id)

        if not args.skip_retrieval:
            from google import genai

            client = genai.Client(api_key=env("GEMINI_API_KEY"))
            embed_model = env("GEMINI_EMBED_MODEL")
            gate_f(conn, client, embed_model, args.book_id, args.sample)
            gate_g(conn, client, embed_model, args.book_id, args.gold)

    failed = [r for r in results if r[1] == FAIL]
    warned = [r for r in results if r[1] == WARN]
    print(
        f"\n{len(results) - len(failed) - len(warned)} passed, "
        f"{len(warned)} warnings, {len(failed)} failed"
    )
    if failed:
        print("\nFAILED:")
        for gate, _, message in failed:
            print(f"  {gate}: {message}")
        raise SystemExit(1)
    print("\nIngestion is good. RAG can be built on this.")


if __name__ == "__main__":
    main()
