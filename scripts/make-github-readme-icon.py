"""Generate the rounded README icon from the square master app icon.

The master icon, ``assets/icons/icon.svg``, is a full-bleed square that each
platform masks itself. GitHub strips CSS from README images, so the README
shows ``icon-github-readme.svg``: the master nested inside an SVG clip path
with rounded corners (radius 22% of the shorter side). Never edit the
generated file by hand; rerun this script whenever ``icon.svg`` changes.

Usage:
    python scripts/make-github-readme-icon.py [path/to/icon.svg] [--check]

The output is written next to the master. ``--check`` writes nothing and exits
1 when the generated file is missing or out of date. Requires Python 3.11+ and
only the standard library.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_MASTER = Path("assets/icons/icon.svg")
OUTPUT_NAME = "icon-github-readme.svg"
SCRIPT = "scripts/make-github-readme-icon.py"
CORNER_RATIO = 0.22
CLIP_ID = "github-readme-corners"
SVG_NS = "http://www.w3.org/2000/svg"

# A start tag whose quoted attribute values may contain ">".
_ROOT_TAG = re.compile(r"<svg\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*?(/?)>")
_ROOT_END = re.compile(r"</svg\s*>")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ATTR = re.compile(
    r"\s+([A-Za-z_:][-A-Za-z0-9_.:]*)\s*=\s*(\"[^\"]*\"|'[^']*')"
)
_LENGTH = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*(px)?\s*$")
_REPLACED_ATTRS = {"x", "y", "width", "height"}


class IconError(Exception):
    """The master icon cannot be turned into a README icon."""


def fmt(value: float) -> str:
    """Format a number compactly and deterministically."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def parse_length(raw: str | None) -> float | None:
    """Return a unitless or px length, or None when absent or relative."""
    if raw is None:
        return None
    match = _LENGTH.match(raw)
    return float(match.group(1)) if match else None


def read_box(root: ET.Element) -> tuple[float, float, float, float]:
    """Return the master's viewBox, falling back to its width and height."""
    view_box = root.get("viewBox")
    if view_box is not None:
        parts = view_box.replace(",", " ").split()
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            numbers = []
        if len(numbers) != 4 or numbers[2] <= 0 or numbers[3] <= 0:
            raise IconError(
                f"viewBox {view_box!r} is not four numbers with a positive size"
            )
        return numbers[0], numbers[1], numbers[2], numbers[3]
    width = parse_length(root.get("width"))
    height = parse_length(root.get("height"))
    if not width or not height:
        raise IconError(
            "the root <svg> has no viewBox and no numeric width and height; "
            'add viewBox="0 0 <width> <height>" to the master'
        )
    return 0.0, 0.0, width, height


def build(master_text: str, master_name: str) -> str:
    """Return the README icon SVG for the given master SVG text."""
    text = (
        master_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    )
    if "<!ENTITY" in text:
        raise IconError(
            "the master declares DTD entities, which cannot be nested"
        )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise IconError(
            f"the master is not well-formed XML: {error}"
        ) from error
    if root.tag != f"{{{SVG_NS}}}svg":
        raise IconError(
            f"the root element is {root.tag!r}, not an SVG <svg> element"
        )
    min_x, min_y, width, height = read_box(root)

    comments = [match.span() for match in _COMMENT.finditer(text)]

    def outside_comments(position: int) -> bool:
        return not any(first <= position < last for first, last in comments)

    start = next(
        (
            match
            for match in _ROOT_TAG.finditer(text)
            if outside_comments(match.start())
        ),
        None,
    )
    if start is None:
        raise IconError("could not locate the root <svg> start tag")
    self_closing = start.group(1) == "/"
    if self_closing:
        end = start.end()
    else:
        closings = [
            match.end()
            for match in _ROOT_END.finditer(text, start.end())
            if outside_comments(match.start())
        ]
        if not closings:
            raise IconError("could not locate the closing </svg> tag")
        end = closings[-1]

    attrs = [
        (name, value)
        for name, value in _ATTR.findall(start.group(0))
        if name not in _REPLACED_ATTRS
    ]
    if not any(name == "viewBox" for name, _ in attrs):
        box = f"{fmt(min_x)} {fmt(min_y)} {fmt(width)} {fmt(height)}"
        attrs.append(("viewBox", f'"{box}"'))
    attrs += [
        ("x", f'"{fmt(min_x)}"'),
        ("y", f'"{fmt(min_y)}"'),
        ("width", f'"{fmt(width)}"'),
        ("height", f'"{fmt(height)}"'),
    ]
    nested_tag = "<svg" + "".join(f" {name}={value}" for name, value in attrs)
    nested_tag += "/>" if self_closing else ">"
    nested = nested_tag + text[start.end() : end]

    outer = [f'xmlns="{SVG_NS}"']
    outer.append(
        f'viewBox="{fmt(min_x)} {fmt(min_y)} {fmt(width)} {fmt(height)}"'
    )
    for name in ("width", "height"):
        value = root.get(name)
        if value is not None:
            outer.append(f'{name}="{value}"')
    radius = fmt(CORNER_RATIO * min(width, height))
    clip_rect = (
        f'<rect x="{fmt(min_x)}" y="{fmt(min_y)}" width="{fmt(width)}"'
        f' height="{fmt(height)}" rx="{radius}" ry="{radius}"/>'
    )
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!--",
        f"  Generated from {master_name} by {SCRIPT}.",
        "  Do not edit by hand: change the master icon and rerun the script.",
        "  The master is nested unchanged inside a rounded-corner clip path",
        "  because GitHub strips CSS from README images.",
        "-->",
        f"<svg {' '.join(outer)}>",
        "  <defs>",
        f'    <clipPath id="{CLIP_ID}">',
        f"      {clip_rect}",
        "    </clipPath>",
        "  </defs>",
        f'  <g clip-path="url(#{CLIP_ID})">',
        nested,
        "  </g>",
        "</svg>",
        "",
    ]
    output = "\n".join(lines)
    try:
        ET.fromstring(output)
    except ET.ParseError as error:
        raise IconError(
            f"the generated SVG is not well-formed: {error}"
        ) from error
    return output


def main(argv: list[str] | None = None) -> int:
    """Generate or check the README icon and return the exit status."""
    parser = argparse.ArgumentParser(
        description="Write the master icon with rounded corners for READMEs.",
    )
    parser.add_argument(
        "master",
        nargs="?",
        type=Path,
        default=DEFAULT_MASTER,
        help=f"master SVG (default: {DEFAULT_MASTER.as_posix()})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if the output is missing or stale",
    )
    args = parser.parse_args(argv)
    master: Path = args.master
    output = master.with_name(OUTPUT_NAME)
    if master.resolve() == output.resolve():
        print(
            f"error: {master} is the generated file, not the master",
            file=sys.stderr,
        )
        return 2
    try:
        master_text = master.read_bytes().decode("utf-8")
    except FileNotFoundError:
        print(f"error: master icon {master} not found", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"error: {master} is not UTF-8 text", file=sys.stderr)
        return 2
    try:
        expected = build(master_text, master.name).encode("utf-8")
    except IconError as error:
        print(f"error: {master}: {error}", file=sys.stderr)
        return 2

    if args.check:
        if not output.is_file():
            print(
                f"{output} is missing; run {SCRIPT}",
                file=sys.stderr,
            )
            return 1
        if output.read_bytes() != expected:
            print(
                f"{output} is out of date; run {SCRIPT}",
                file=sys.stderr,
            )
            return 1
        print(f"{output} is up to date")
        return 0

    if output.is_file() and output.read_bytes() == expected:
        print(f"{output} is already up to date")
    else:
        output.write_bytes(expected)
        print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
