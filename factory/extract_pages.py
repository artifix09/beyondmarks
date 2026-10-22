"""Stage 2 — PDF pages to image files.

The book is 222 scanned pages with no text layer, so every page has to be
handed to a vision model as an image. Two ways to get one, and the choice
matters:

  extract  Pull the embedded scan straight out of the PDF. Lossless, fast, and
           native resolution. Works when the page is a single full-page image,
           which is what a scanned book normally is.

  render   Rasterise the page at a chosen DPI. Needed when a page is built
           from several images or has vector content drawn over the scan.

`auto` picks per page. Run inspect_pdf.py first: it prints the native scan DPI,
and rendering above it buys nothing but tokens.

Usage:
    python -I extract_pages.py book.pdf --out ./work/pages --page-map page_map.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz  # pymupdf

# Running with -I (isolated) drops the script's own directory from sys.path,
# so the sibling imports below need it put back explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import Manifest, PageMap


def page_is_single_scan(page: fitz.Page, doc: fitz.Document) -> tuple[bool, int]:
    """True when one embedded image covers the page. Returns its xref too."""
    images = page.get_images(full=True)
    if len(images) != 1:
        return False, 0
    xref = images[0][0]
    info = doc.extract_image(xref)
    rect = page.rect
    # A scan is roughly page-shaped and much denser than 72 dpi.
    covers = info["width"] * info["height"] > 0.5 * (rect.width * rect.height) * 4
    return covers, xref


def extract(
    pdf_path: Path,
    out_dir: Path,
    *,
    mode: str,
    dpi: int,
    pages: list[int] | None,
    force: bool,
) -> None:
    doc = fitz.open(pdf_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(out_dir / "manifest.jsonl", key="pdf_index")

    targets = pages or list(range(1, doc.page_count + 1))
    print(f"{pdf_path.name}: {doc.page_count} pages, extracting {len(targets)}")

    written = skipped = 0
    for pdf_index in targets:
        if not force and manifest.has(pdf_index):
            skipped += 1
            continue

        page = doc[pdf_index - 1]
        single, xref = page_is_single_scan(page, doc)
        use_extract = mode == "extract" or (mode == "auto" and single)

        try:
            if use_extract and xref:
                info = doc.extract_image(xref)
                path = out_dir / f"page_{pdf_index:04d}.{info['ext']}"
                path.write_bytes(info["image"])
                how, width, height = "extract", info["width"], info["height"]
            else:
                pix = page.get_pixmap(dpi=dpi)
                path = out_dir / f"page_{pdf_index:04d}.png"
                pix.save(path)
                how, width, height = "render", pix.width, pix.height

            manifest.record(
                {
                    "pdf_index": pdf_index,
                    "status": "ok",
                    "file": path.name,
                    "method": how,
                    "width": width,
                    "height": height,
                    "bytes": path.stat().st_size,
                }
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            manifest.record(
                {"pdf_index": pdf_index, "status": "error", "error": str(exc)}
            )
            print(f"  page {pdf_index}: {exc}", file=sys.stderr)

        if written and written % 25 == 0:
            print(f"  {written} written", flush=True)

    doc.close()

    methods = {}
    for row in manifest.rows():
        if row.get("status") == "ok":
            methods[row.get("method")] = methods.get(row.get("method"), 0) + 1

    print(f"\nwritten {written}, skipped {skipped} already done")
    print(f"methods: {methods}")
    if manifest.failed:
        print(f"FAILED {len(manifest.failed)}: {[r['pdf_index'] for r in manifest.failed][:20]}")
    print(f"-> {out_dir.resolve()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, default=Path("./work/pages"))
    ap.add_argument("--mode", choices=["auto", "extract", "render"], default="auto")
    ap.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="render DPI; match the native scan DPI from inspect_pdf.py",
    )
    ap.add_argument(
        "--page-map",
        type=Path,
        help="only extract pages inside mapped chapters, skipping front matter",
    )
    ap.add_argument("--force", action="store_true", help="redo pages already done")
    args = ap.parse_args()

    pages = None
    if args.page_map:
        pages = PageMap.from_csv(args.page_map).content_pages()
        print(f"page map limits extraction to {len(pages)} content pages")

    extract(
        args.pdf,
        args.out,
        mode=args.mode,
        dpi=args.dpi,
        pages=pages,
        force=args.force,
    )


if __name__ == "__main__":
    main()
