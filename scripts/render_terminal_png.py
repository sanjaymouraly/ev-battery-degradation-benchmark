#!/usr/bin/env python3
"""Render a captured terminal transcript into a PNG image.

This is a *renderer*: it reads a text transcript that was produced by actually
running the commands (see ``docs/cli-transcript.txt``) and draws it with a
monospace font in a terminal-like frame.  It does not execute anything and it
does not invent output -- the pixels correspond one-to-one to the text file.

Usage::

    python scripts/render_terminal_png.py docs/cli-transcript.txt \\
        -o docs/images/cli-terminal.png --title "evbatt CLI — real LFP data"
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
]
BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
]

BG = (22, 24, 30)
CHROME = (38, 41, 50)
BORDER = (58, 62, 74)
FG = (208, 212, 222)
PROMPT = (126, 214, 160)
COMMENT = (110, 118, 134)
KEY = (129, 190, 240)
ERROR = (240, 130, 130)
TITLE = (150, 156, 170)


def _pick(paths: list[str]) -> str:
    for p in paths:
        if Path(p).is_file():
            return p
    raise SystemExit("no monospace TTF font found; install fonts-dejavu-core")


def _wrap(text: str, width: int) -> list[str]:
    """Wrap on word boundaries, never splitting a token that fits on a line."""
    out: list[str] = []
    for raw in text.splitlines() or [""]:
        if len(raw) <= width:
            out.append(raw)
            continue
        indent = len(raw) - len(raw.lstrip())
        cur = ""
        for word in raw.split():
            candidate = f"{cur} {word}".strip() if cur else raw[:indent] + word
            if len(candidate) <= width:
                cur = candidate
            else:
                if cur:
                    out.append(cur)
                cur = raw[:indent] + word
        if cur:
            out.append(cur)
    return out


def _tokenize(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    """Very small highlighter: prompt, comment lines, and JSON keys/values."""
    if line.startswith("#"):
        return [(line, COMMENT)]
    if line.startswith("$ "):
        cmd = line[2:]
        parts = cmd.split(" ")
        coloured: list[tuple[str, tuple[int, int, int]]] = [("$ ", PROMPT)]
        for i, tok in enumerate(parts):
            if i:
                coloured.append((" ", FG))
            if tok.startswith('"') or tok.startswith("'"):
                coloured.append((tok, KEY))
            elif re.fullmatch(r"[A-Za-z_][\w./-]*", tok):
                coloured.append((tok, FG))
            else:
                coloured.append((tok, KEY))
        return coloured
    stripped = line.strip()
    if stripped.startswith('"') and ":" in stripped:
        key, _, rest = stripped.partition(":")
        return [(key, KEY), (":" + rest, FG)]
    if stripped in {"}", "},", "],", "]"}:
        return [(line, FG)]
    if re.search(r"\bTraceback\b|\bError\b|\bException\b", line):
        return [(line, ERROR)]
    return [(line, FG)]


def render(text: str, out_path: Path, title: str, cols: int = 118, font_size: int = 15) -> Path:
    lines: list[str] = []
    for raw in text.splitlines():
        lines.extend(_wrap(raw, cols))
    while lines and not lines[-1].strip():
        lines.pop()

    mono = ImageFont.truetype(_pick(MONO_CANDIDATES), font_size)
    bold = ImageFont.truetype(_pick(BOLD_CANDIDATES), font_size)
    title_font = ImageFont.truetype(_pick(BOLD_CANDIDATES), font_size - 2)

    probe = Image.new("RGB", (10, 10))
    d0 = ImageDraw.Draw(probe)
    bbox = d0.textbbox((0, 0), "M", font=mono)
    cw = bbox[2] - bbox[0]
    ch = int((bbox[3] - bbox[1]) * 1.55)

    pad = 18
    gutter = 14
    title_h = 40
    width = pad * 2 + gutter + cw * cols
    height = title_h + pad * 2 + ch * len(lines)

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    # Window chrome.
    d.rectangle([0, 0, width, title_h], fill=CHROME)
    d.line([(0, title_h), (width, title_h)], fill=BORDER)
    for i, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 20 + i * 20
        d.ellipse([cx - 6, title_h // 2 - 6, cx + 6, title_h // 2 + 6], fill=colour)
    d.text((90, title_h // 2 - (bbox[3] - bbox[1]) // 2 - 2), title, font=title_font, fill=TITLE)

    # Gutter (line numbers).
    x0 = pad + gutter
    y = title_h + pad
    for i, line in enumerate(lines, start=1):
        d.text((pad, y), f"{i:>3}", font=mono, fill=(78, 84, 98))
        x = x0
        for token, colour in _tokenize(line):
            d.text((x, y), token, font=bold if token.startswith("$ ") else mono, fill=colour)
            x += cw * len(token)
        y += ch

    d.rectangle([0, 0, width - 1, height - 1], outline=BORDER)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("docs/images/cli-terminal.png"))
    ap.add_argument("--title", default="terminal")
    ap.add_argument("--cols", type=int, default=118)
    ap.add_argument("--font-size", type=int, default=15)
    args = ap.parse_args()
    text = args.transcript.read_text(encoding="utf-8")
    path = render(text, args.output, args.title, args.cols, args.font_size)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
