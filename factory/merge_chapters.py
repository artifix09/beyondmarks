"""Stage 0b - chapter PDFs into one book, plus a page-map skeleton.

The book arrived split into one PDF per chapter. The rest of the pipeline
works on a single book with one page numbering, so this joins them back
together in order.

The useful part is the second output. Because this script knows how many pages
each chapter contributed, it can fill in `pdf_start` and `pdf_end` for every
chapter itself. That leaves exactly one number per chapter for a human to
type: the page number printed on the chapter's first page. Three numbers per
chapter typed by hand is three chances to transpose a digit, and a wrong
offset puts every citation in that chapter on the wrong page.

Usage:
    python -I merge_chapters.py ./chapters --out ./work/physics9.pdf
    python -I merge_chapters.py ./chapters --out ./work/physics9.pdf --order order.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fitz  # pymupdf

NUMBER_RE = re.compile(r"(\d+)")


def chapter_number(path: Path) -> int | None:
    """First number in the filename: ch1.pdf, Chapter 02.pdf, unit-3-final.pdf."""
    match = NUMBER_RE.search(path.stem)
    return int(match.group(1)) if match else None


def clean_title(path: Path) -> str:
    """A readable chapter title from the filename, for the page map."""
    stem = re.sub(r"^(chapter|chap|ch|unit)[\s_-]*\d*", "", path.stem, flags=re.I)
    stem = re.sub(r"[_-]+", " ", stem)
    return re.sub(r"\s+", " ", stem).strip().title() or path.stem


def ordered_chapters(folder: Path, order_file: Path | None) -> list[Path]:
    if order_file:
        names = [
            line.strip()
            for line in order_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        paths = [folder / n for n in names]
        missing = [p.name for p in paths if not p.exists()]
        if missing:
            sys.exit(f"listed in {order_file} but not found: {missing}")
        return paths

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"no PDFs in {folder}")

    numbered = [(chapter_number(p), p) for p in pdfs]
    if any(n is None for n, _ in numbered):
        unnumbered = [p.name for n, p in numbered if n is None]
        print(
            f"WARNING: no chapter number in the filename for {unnumbered}. "
            "Falling back to alphabetical order, which sorts ch10 before ch2.\n"
            "  Check the order printed below, and use --order with a text file "
            "listing the filenames if it is wrong."
        )
        return pdfs

    return [p for _, p in sorted(numbered, key=lambda pair: pair[0])]


def merge(folder: Path, out_pdf: Path, order_file: Path | None, map_path: Path) -> None:
    chapters = ordered_chapters(folder, order_file)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    book = fitz.open()
    rows: list[dict] = []
    cursor = 1  # 1-based page index in the merged book

    print(f"{len(chapters)} chapter PDFs\n")
    print(f"{'#':>3}  {'file':<34} {'pages':>5}  {'pdf range':>11}  title")

    for position, path in enumerate(chapters, start=1):
        with fitz.open(path) as chapter:
            n_pages = chapter.page_count
            if n_pages == 0:
                print(f"     {path.name:<34} EMPTY - skipped")
                continue
            book.insert_pdf(chapter)

        number = chapter_number(path)
        number = number if number is not None else position
        row = {
            "chapter_no": number,
            "title": clean_title(path),
            "pdf_start": cursor,
            "pdf_end": cursor + n_pages - 1,
            "file": path.name,
        }
        rows.append(row)
        print(
            f"{number:>3}  {path.name[:34]:<34} {n_pages:>5}  "
            f"{row['pdf_start']:>4}-{row['pdf_end']:<6}  {row['title']}"
        )
        cursor += n_pages

    book.save(out_pdf)
    total = book.page_count
    book.close()

    duplicates = [n for n in {r["chapter_no"] for r in rows} if
                  sum(1 for r in rows if r["chapter_no"] == n) > 1]
    if duplicates:
        print(
            f"\nWARNING: chapter number {duplicates} appears more than once. "
            "Fix the filenames or the page map before loading."
        )

    with map_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(
            "# pdf_start and pdf_end were computed from the chapter PDFs.\n"
            "# Fill in printed_start: the page number PRINTED on the first\n"
            "# page of that chapter. Open the merged PDF at pdf_start and read\n"
            "# the number in the corner. Every page citation the student sees\n"
            "# depends on this one number per chapter being right.\n"
            "chapter_no,title,pdf_start,pdf_end,printed_start\n"
        )
        for row in rows:
            fh.write(
                f"{row['chapter_no']},{row['title']},"
                f"{row['pdf_start']},{row['pdf_end']},\n"
            )

    print(f"\nmerged {total} pages -> {out_pdf.resolve()}")
    print(f"page map skeleton  -> {map_path.resolve()}")
    print(
        "\nNEXT\n"
        f"  1. Open {out_pdf.name} and check chapter 1 really starts at the page "
        "the table above says.\n"
        "  2. Fill the printed_start column - one number per chapter.\n"
        f"  3. python -I inspect_pdf.py {out_pdf} --out ./work/pdf_check"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path, help="folder holding the chapter PDFs")
    ap.add_argument("--out", type=Path, default=Path("./work/book.pdf"))
    ap.add_argument(
        "--page-map", type=Path, default=Path("page_map.csv"), dest="map_path"
    )
    ap.add_argument(
        "--order",
        type=Path,
        help="text file listing the chapter filenames in the right order",
    )
    args = ap.parse_args()

    if args.map_path.exists():
        sys.exit(
            f"{args.map_path} already exists - not overwriting it, because it "
            "may hold printed_start values you typed in. Delete it or pass "
            "--page-map with another name."
        )

    merge(args.folder, args.out, args.order, args.map_path)


if __name__ == "__main__":
    main()
