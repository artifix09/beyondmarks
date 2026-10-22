"""Diagnose the textbook PDF before writing any ingestion code.

Answers four questions that decide the whole pipeline:

  1. Is there a real text layer, or is every page an image?
  2. Is the watermark an OVERLAY (removable by extracting the base image) or
     BURNED INTO the scan (needs prompting or image work)?
  3. What is the native resolution of the scans, so we render at the right DPI?
  4. Does the printed page number match the PDF page index, or is there an
     offset from front matter? Citations must use the printed number.

Writes sample pages to an output folder two ways - rendered (what a naive
pipeline sees) and extracted (the base image alone) - so you can compare them
by eye.

Usage:
    pip install pymupdf
    python -I inspect_pdf.py path/to/physics9.pdf --out ./pdf_check
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz  # pymupdf


def sample_indices(total: int, count: int) -> list[int]:
    """Evenly spaced pages, skipping the cover and the last page."""
    if total <= count:
        return list(range(total))
    step = max(1, (total - 2) // count)
    return list(range(1, total - 1, step))[:count]


def inspect(pdf_path: Path, out_dir: Path, n_samples: int) -> dict:
    doc = fitz.open(pdf_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "file": str(pdf_path),
        "pages": doc.page_count,
        "size_mb": round(pdf_path.stat().st_size / 1_048_576, 1),
        "is_encrypted": doc.is_encrypted,
        "metadata": {k: v for k, v in (doc.metadata or {}).items() if v},
        "samples": [],
    }

    pages_with_text = 0
    total_chars = 0
    text_snippets: list[str] = []

    for i in sample_indices(doc.page_count, n_samples):
        page = doc[i]
        text = page.get_text().strip()
        images = page.get_images(full=True)
        drawings = page.get_drawings()
        annots = list(page.annots() or [])

        if text:
            pages_with_text += 1
            total_chars += len(text)
            text_snippets.append(text[:300])

        # Native size of the largest embedded image on the page.
        largest = None
        for img in images:
            xref = img[0]
            info = doc.extract_image(xref)
            px = info["width"] * info["height"]
            if largest is None or px > largest["pixels"]:
                largest = {
                    "xref": xref,
                    "width": info["width"],
                    "height": info["height"],
                    "pixels": px,
                    "ext": info["ext"],
                }

        rect = page.rect
        covers_page = False
        approx_dpi = None
        if largest:
            # A single image covering the page means the page IS a scan.
            covers_page = largest["pixels"] > 0.5 * (rect.width * rect.height) * 4
            if rect.width:
                approx_dpi = round(largest["width"] / (rect.width / 72))

        report["samples"].append(
            {
                "page_index": i,
                "pdf_page_label": page.get_label() or None,
                "text_chars": len(text),
                "image_count": len(images),
                "vector_drawings": len(drawings),
                "annotations": len(annots),
                "largest_image": largest,
                "image_covers_page": covers_page,
                "approx_scan_dpi": approx_dpi,
                "page_points": [round(rect.width), round(rect.height)],
            }
        )

        # Rendered: image + any overlay composited together.
        page.get_pixmap(dpi=200).save(out_dir / f"page{i:04d}_rendered.png")

        # Extracted: the base scan alone. If the watermark is an overlay, it
        # is absent here - that comparison is the whole point of this script.
        if largest:
            info = doc.extract_image(largest["xref"])
            (out_dir / f"page{i:04d}_extracted.{info['ext']}").write_bytes(
                info["image"]
            )

    report["text_layer"] = {
        "sample_pages_with_text": pages_with_text,
        "avg_chars_on_those_pages": (
            round(total_chars / pages_with_text) if pages_with_text else 0
        ),
        "snippets": text_snippets[:3],
    }

    # Verdict.
    avg = report["text_layer"]["avg_chars_on_those_pages"]
    if pages_with_text == 0:
        verdict = (
            "NO TEXT LAYER. Pure scan. Vision transcription is the only option, "
            "and any watermark is either an image overlay or burned in - compare "
            "the rendered and extracted PNGs to find out which."
        )
    elif avg < 200:
        verdict = (
            "TINY TEXT LAYER on a scanned page - this is almost certainly the "
            "WATERMARK ITSELF as a text overlay, not book content. Read the "
            "snippets below. If they are the watermark, extract the base image "
            "instead of rendering and the watermark disappears entirely."
        )
    else:
        verdict = (
            "REAL TEXT LAYER present. Check a snippet: if the book text is "
            "there, formulas are still likely mangled, so vision transcription "
            "stays the plan - but the text layer is a free cross-check."
        )
    report["verdict"] = verdict

    doc.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, default=Path("./pdf_check"))
    ap.add_argument("--samples", type=int, default=8)
    args = ap.parse_args()

    report = inspect(args.pdf, args.out, args.samples)

    (args.out / "report.json").write_text(json.dumps(report, indent=2))

    print(f"\n{report['pages']} pages, {report['size_mb']} MB")
    print(f"\nVERDICT\n  {report['verdict']}\n")

    if report["text_layer"]["snippets"]:
        print("TEXT LAYER SNIPPETS (is this the book, or the watermark?)")
        for s in report["text_layer"]["snippets"]:
            print(f"  | {s[:160]!r}")
        print()

    print(f"{'page':>6} {'chars':>6} {'imgs':>5} {'vectors':>8} {'scan dpi':>9}  full-page")
    for s in report["samples"]:
        print(
            f"{s['page_index']:>6} {s['text_chars']:>6} {s['image_count']:>5} "
            f"{s['vector_drawings']:>8} {str(s['approx_scan_dpi']):>9}  "
            f"{'yes' if s['image_covers_page'] else 'no'}"
        )

    print(f"\nSample PNGs and report.json written to {args.out.resolve()}")
    print(
        "\nNEXT: open one *_rendered.png and the matching *_extracted.* side by "
        "side.\n"
        "  watermark in rendered, absent in extracted -> OVERLAY, extract and we are done\n"
        "  watermark in both                          -> BURNED IN, handle it in the prompt\n"
        "  no extracted file written                  -> page is vector/text, not a scan"
    )


if __name__ == "__main__":
    main()
