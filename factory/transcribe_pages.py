"""Stage 3 — page images to Markdown, through Gemini vision.

One call per page, several in flight at once, every result appended to a
manifest as it lands. Re-running skips pages already transcribed, so a dropped
Colab runtime or an exhausted rate limit costs the page in flight and nothing
more.

The model returns structured JSON, not free text, because a transcription that
needs parsing from prose fails on exactly the pages that matter most: the ones
dense with formulas.

Usage:
    python -I transcribe_pages.py --pages ./work/pages --out ./work/transcripts
    python -I transcribe_pages.py --pages ./work/pages --out ./work/transcripts --only 14,15,16
"""

from __future__ import annotations

import argparse
import sys
import json
import mimetypes
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Running with -I (isolated) drops the script's own directory from sys.path,
# so the sibling imports below need it put back explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import Manifest, env, with_retry

PROMPT_PATH = Path(__file__).parent / "prompts" / "transcribe_page.md"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "printed_page": {"type": "integer", "nullable": True},
        "page_kind": {
            "type": "string",
            "enum": [
                "content",
                "contents",
                "exercises",
                "index",
                "blank",
                "front_matter",
            ],
        },
        "has_math": {"type": "boolean"},
        "has_figure": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "notes": {"type": "string", "nullable": True},
    },
    "required": ["markdown", "page_kind", "has_math", "has_figure", "confidence"],
}


def load_prompt() -> tuple[str, str]:
    """Returns (prompt text, version). The version is logged with every page.

    A change in transcription quality has to be traceable to the prompt that
    caused it, which is the same rule the API follows for llm_calls.
    """
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    version = "0"
    match = re.match(r"^---\n(.*?)\n---\n", raw, flags=re.DOTALL)
    body = raw
    if match:
        for line in match.group(1).splitlines():
            if line.startswith("version:"):
                version = line.split(":", 1)[1].strip()
        body = raw[match.end() :]
    return body.strip(), version


def transcribe_one(client, model: str, prompt: str, image_path: Path) -> dict:
    from google.genai import types

    mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
    data = image_path.read_bytes()

    def call():
        return client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.0,  # transcription, not writing
            ),
        )

    response = with_retry(call, what=f"transcribe {image_path.name}")
    return json.loads(response.text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=Path, default=Path("./work/pages"))
    ap.add_argument("--out", type=Path, default=Path("./work/transcripts"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", help="comma separated PDF page indices, for a pilot run")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    from google import genai

    client = genai.Client(api_key=env("GEMINI_API_KEY"))
    model = env("GEMINI_MODEL")
    prompt, prompt_version = load_prompt()

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(args.out / "manifest.jsonl", key="pdf_index")

    images = sorted(args.pages.glob("page_*.*"))
    images = [p for p in images if p.suffix.lower() != ".jsonl"]
    if args.only:
        wanted = {int(x) for x in args.only.split(",")}
        images = [p for p in images if int(p.stem.split("_")[1]) in wanted]

    todo = [
        p
        for p in images
        if args.force or not manifest.has(int(p.stem.split("_")[1]))
    ]
    print(
        f"{len(images)} page images, {len(todo)} to do "
        f"({len(images) - len(todo)} already transcribed)"
    )
    print(f"model {model}, prompt {prompt_version}, {args.workers} workers\n")

    def work(path: Path) -> tuple[Path, dict | None, str | None]:
        try:
            return path, transcribe_one(client, model, prompt, path), None
        except Exception as exc:  # noqa: BLE001
            return path, None, str(exc)

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(work, p) for p in todo]
        for future in as_completed(futures):
            path, result, error = future.result()
            pdf_index = int(path.stem.split("_")[1])

            if error or result is None:
                manifest.record(
                    {"pdf_index": pdf_index, "status": "error", "error": error}
                )
                print(f"  page {pdf_index}: FAILED {error}")
                continue

            md_path = args.out / f"page_{pdf_index:04d}.md"
            md_path.write_text(result.get("markdown", ""), encoding="utf-8")

            manifest.record(
                {
                    "pdf_index": pdf_index,
                    "status": "ok",
                    "file": md_path.name,
                    "chars": len(result.get("markdown", "")),
                    "printed_page": result.get("printed_page"),
                    "page_kind": result.get("page_kind"),
                    "has_math": result.get("has_math"),
                    "has_figure": result.get("has_figure"),
                    "confidence": result.get("confidence"),
                    "notes": result.get("notes"),
                    "model": model,
                    "prompt_version": prompt_version,
                }
            )
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(todo)}", flush=True)

    rows = [r for r in manifest.rows() if r.get("status") == "ok"]
    low = [r for r in rows if r.get("confidence") == "low"]
    noted = [r for r in rows if r.get("notes")]

    print(f"\ntranscribed {manifest.ok_count} pages total")
    if low:
        print(f"LOW CONFIDENCE on {len(low)}: {[r['pdf_index'] for r in low][:25]}")
        print("  read these against the PDF before trusting them")
    if noted:
        print(f"notes on {len(noted)}: {[r['pdf_index'] for r in noted][:25]}")
    if manifest.failed:
        print(f"FAILED {len(manifest.failed)}: {[r['pdf_index'] for r in manifest.failed][:25]}")
        print("  re-run the same command; finished pages are skipped")
    print(f"-> {args.out.resolve()}")


if __name__ == "__main__":
    main()
