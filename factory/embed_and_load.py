"""Stages 4-6 — transcripts to chunks to embeddings to textbook_chunks.

Chunking itself lives in chunker.py, where it is unit tested. This script
wires it to the page map, the embedding model and the database.

Two details that are easy to get wrong and expensive to find later:

  task type   Documents are embedded as RETRIEVAL_DOCUMENT and queries as
              RETRIEVAL_QUERY. They are different vectors from the same model.
              Mixing them up costs accuracy that looks exactly like bad
              chunking.

  dimensions  textbook_chunks.embedding is vector(768) and the index is
              cosine. Gemini normalises its embeddings at full width only, so
              a 768-dim output has to be re-normalised here.

Usage:
    python -I embed_and_load.py --book-id <uuid> --page-map page_map.csv \
        --transcripts ./work/transcripts
"""

from __future__ import annotations

import argparse
import sys
import math
from pathlib import Path

# Running with -I (isolated) drops the script's own directory from sys.path,
# so the sibling imports below need it put back explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chunker import Chunk, PageText, chunk_pages
from common import Manifest, PageMap, connect, env, with_retry

EMBED_DIM = 768
EMBED_BATCH = 50
# Pages that are not teaching content still get ingested when the whole book
# is wanted, but these never are: they retrieve as noise.
SKIP_KINDS = {"blank", "index", "contents", "front_matter"}


def load_pages(transcripts: Path, page_map: PageMap) -> list[PageText]:
    """Transcribed pages in order, with the printed page number attached.

    The printed number comes from the page map, not from the model's reading
    of the page: the map is checked by a human and the model's guess is not.
    Where the two disagree the map wins, and the disagreement is reported.
    """
    manifest = Manifest(transcripts / "manifest.jsonl", key="pdf_index")
    pages: list[PageText] = []
    mismatches: list[tuple[int, int | None, int | None]] = []

    for row in sorted(manifest.rows(), key=lambda r: r["pdf_index"]):
        if row.get("status") != "ok":
            continue
        if row.get("page_kind") in SKIP_KINDS:
            continue

        pdf_index = row["pdf_index"]
        mapped = page_map.printed_page(pdf_index)
        if mapped is None:
            continue  # outside every mapped chapter

        seen = row.get("printed_page")
        if seen is not None and seen != mapped:
            mismatches.append((pdf_index, seen, mapped))

        md = (transcripts / row["file"]).read_text(encoding="utf-8")
        if md.strip():
            pages.append(
                PageText(pdf_index=pdf_index, printed_page=mapped, markdown=md)
            )

    if mismatches:
        print(
            f"WARNING: page map disagrees with the printed number on "
            f"{len(mismatches)} pages. Using the map. First few "
            f"(pdf, on page, mapped): {mismatches[:8]}"
        )
        print("  If there are many, the page map offset is wrong - fix it first.")

    return pages


def normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def embed_all(client, model: str, texts: list[str]) -> list[list[float]]:
    from google.genai import types

    out: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start : start + EMBED_BATCH]

        def call():
            return client.models.embed_content(
                model=model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBED_DIM,
                ),
            )

        response = with_retry(call, what=f"embed {start}-{start + len(batch)}")
        for item in response.embeddings:
            vector = list(item.values)
            if len(vector) != EMBED_DIM:
                raise SystemExit(
                    f"{model} returned {len(vector)} dimensions, not {EMBED_DIM}. "
                    "textbook_chunks.embedding is vector(768) — pick a model "
                    "that can output 768, or change the schema and the index."
                )
            out.append(normalise(vector))
        print(f"  embedded {len(out)}/{len(texts)}", flush=True)
    return out


def chapter_ids(conn, book_id: str) -> dict[int, str]:
    with conn.cursor() as cur:
        cur.execute(
            "select id, number from chapters where book_id = %s order by number",
            (book_id,),
        )
        return {row["number"]: row["id"] for row in cur.fetchall()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-id", required=True)
    ap.add_argument("--page-map", type=Path, required=True)
    ap.add_argument("--transcripts", type=Path, default=Path("./work/transcripts"))
    ap.add_argument(
        "--replace",
        action="store_true",
        help="delete this book's existing chunks first — use when re-ingesting",
    )
    ap.add_argument("--dry-run", action="store_true", help="chunk only, no API, no writes")
    args = ap.parse_args()

    page_map = PageMap.from_csv(args.page_map)
    all_pages = load_pages(args.transcripts, page_map)
    print(f"{len(all_pages)} transcribed content pages across {len(page_map.rows)} chapters")

    # Chunk per chapter: a chunk must never span two chapters.
    per_chapter: list[tuple[int, Chunk]] = []
    for row in page_map.rows:
        pages = [
            p for p in all_pages if row["pdf_start"] <= p.pdf_index <= row["pdf_end"]
        ]
        if not pages:
            print(f"  chapter {row['chapter_no']} {row['title']}: no pages, skipped")
            continue
        chunks = chunk_pages(pages)
        per_chapter.extend((row["chapter_no"], c) for c in chunks)
        words = [c.words for c in chunks]
        print(
            f"  chapter {row['chapter_no']:>2} {row['title'][:34]:<34} "
            f"{len(pages):>3} pages -> {len(chunks):>3} chunks "
            f"({min(words)}-{max(words)} words)"
        )

    if not per_chapter:
        raise SystemExit("no chunks produced - check the page map against the transcripts")

    print(f"\n{len(per_chapter)} chunks total")

    if args.dry_run:
        print("dry run: nothing embedded, nothing written")
        return

    texts = [
        f"{chunk.heading}\n{chunk.content}" if chunk.heading else chunk.content
        for _, chunk in per_chapter
    ]

    from google import genai

    client = genai.Client(api_key=env("GEMINI_API_KEY"))
    embed_model = env("GEMINI_EMBED_MODEL")
    print(f"embedding with {embed_model} at {EMBED_DIM} dimensions")
    vectors = embed_all(client, embed_model, texts)

    model_tag = f"{embed_model}@{EMBED_DIM}"
    with connect() as conn:
        ids = chapter_ids(conn, args.book_id)
        missing = {no for no, _ in per_chapter} - set(ids)
        if missing:
            raise SystemExit(
                f"no chapters row for chapter number(s) {sorted(missing)} of this "
                "book. Seed chapters before loading chunks."
            )

        with conn.cursor() as cur:
            if args.replace:
                cur.execute(
                    "delete from textbook_chunks where book_id = %s", (args.book_id,)
                )
                print(f"deleted {cur.rowcount} existing chunks for this book")

            for (chapter_no, chunk), vector in zip(per_chapter, vectors, strict=True):
                cur.execute(
                    """
                    insert into textbook_chunks
                        (book_id, chapter_id, heading, content,
                         page_start, page_end, source, embedding, embedding_model)
                    values (%s, %s, %s, %s, %s, %s, 'textbook', %s, %s)
                    """,
                    (
                        args.book_id,
                        ids[chapter_no],
                        chunk.heading,
                        chunk.content,
                        chunk.page_start,
                        chunk.page_end,
                        str(vector),
                        model_tag,
                    ),
                )
        conn.commit()

    print(f"\nloaded {len(per_chapter)} chunks as {model_tag}")
    print("next: python -I validate_ingestion.py --book-id " + args.book_id)


if __name__ == "__main__":
    main()
