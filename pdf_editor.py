from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import fitz

Color = Tuple[float, float, float]


@dataclass
class TextSpan:
    text: str
    bbox: Tuple[float, float, float, float]
    origin: Tuple[float, float]
    font_name: str
    size: float
    color: Color
    bold: bool
    italic: bool
    serifed: bool


def _int_to_rgb(value: int) -> Color:
    r = ((value >> 16) & 255) / 255
    g = ((value >> 8) & 255) / 255
    b = (value & 255) / 255
    return (r, g, b)


def spans_for_page(page: fitz.Page) -> List[TextSpan]:
    spans: List[TextSpan] = []
    raw = page.get_text('dict')
    for block in raw.get('blocks', []):
        for line in block.get('lines', []):
            for s in line.get('spans', []):
                flags = s.get('flags', 0)
                spans.append(TextSpan(
                    text=s['text'],
                    bbox=tuple(s['bbox']),
                    origin=tuple(s['origin']),
                    font_name=s['font'],
                    size=float(s['size']),
                    color=_int_to_rgb(s['color']),
                    bold=bool(flags & (1 << 4)),
                    italic=bool(flags & (1 << 1)),
                    serifed=bool(flags & (1 << 2)),
                ))
    return spans
