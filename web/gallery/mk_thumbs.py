#!/usr/bin/env python3
"""Generate gallery thumbnails (2C). Run once, check in the SVGs.

Usage: python3 web/gallery/mk_thumbs.py
Source of truth for the data-URIs inlined in web/js/features/gallery.js:
re-run and diff when a thumb changes, then paste the printed JS lines.
Stdlib only.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
BG = "#e8e9ec"
PAPER = "#ffffff"
INK = "#c3c6cd"
ACC = "#4f46e5"


def lines(x, y, widths, gap=9, h=4):
    out = []
    for i, w in enumerate(widths):
        out.append(f'<rect x="{x}" y="{y + i * gap}" width="{w}" height="{h}" rx="2" fill="{INK}"/>')
    return "".join(out)


def doc(w, h, inner, landscape=False):
    pw, ph = (104, 72) if landscape else (72, 104)
    px, py = (w - pw) // 2, (h - ph) // 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="{BG}"/>'
            f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="3" fill="{PAPER}"/>'
            f"{inner(px, py, pw, ph)}</svg>")


def blank():
    return doc(120, 150, lambda px, py, pw, ph: "")


def report():
    def inner(px, py, pw, ph):
        return (f'<rect x="{px + 10}" y="{py + 12}" width="{pw - 20}" height="8" rx="2" fill="{ACC}"/>' +
                lines(px + 10, py + 28, [pw - 20, pw - 20, pw - 28, pw - 20, pw - 34]))
    return doc(120, 150, inner)


def slides():
    def inner(px, py, pw, ph):
        return (f'<rect x="{px + 8}" y="{py + 10}" width="40" height="7" rx="2" fill="{ACC}"/>' +
                lines(px + 8, py + 24, [60, 52, 64]))
    return doc(160, 110, inner, landscape=True)


def paper():
    def inner(px, py, pw, ph):
        return (f'<rect x="{px + 14}" y="{py + 10}" width="{pw - 28}" height="7" rx="2" fill="{ACC}"/>' +
                lines(px + 10, py + 26, [pw - 20, pw - 20, 30, pw - 20, pw - 26]))
    return doc(120, 150, inner)


def cv():
    def inner(px, py, pw, ph):
        return (f'<circle cx="{px + 18}" cy="{py + 18}" r="8" fill="{ACC}"/>' +
                f'<rect x="{px + 30}" y="{py + 12}" width="26" height="6" rx="2" fill="{ACC}"/>' +
                lines(px + 10, py + 36, [pw - 20, pw - 20, pw - 30, pw - 20]))
    return doc(120, 150, inner)


def letter():
    def inner(px, py, pw, ph):
        return (lines(px + 34, py + 10, [28, 22]) +
                lines(px + 10, py + 44, [pw - 20, pw - 20, pw - 20, pw - 34]))
    return doc(120, 150, inner)


def thesis():
    def inner(px, py, pw, ph):
        return (f'<rect x="{px}" y="{py + 18}" width="{pw}" height="20" fill="{ACC}"/>' +
                f'<rect x="{px + 12}" y="{py + 24}" width="{pw - 24}" height="6" rx="2" fill="#fff"/>' +
                lines(px + 10, py + 50, [pw - 20, pw - 28, pw - 20]))
    return doc(120, 150, inner)


def main():
    thumbs = {"blank": blank(), "report": report(), "slides": slides(),
              "paper": paper(), "cv": cv(), "letter": letter(), "thesis": thesis()}
    for name, svg in thumbs.items():
        (HERE / f"{name}.svg").write_text(svg, encoding="utf-8")
    print("wrote", len(thumbs), "thumbs")
    print("--- paste into gallery.js THUMBS (single-line each): ---")
    for name, svg in thumbs.items():
        one = " ".join(svg.split())
        print(f"  {name}: '{one}',")


if __name__ == "__main__":
    main()
