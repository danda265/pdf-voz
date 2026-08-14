from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

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


@dataclass
class FormatOverride:
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    size: Optional[float] = None
    color: Optional[Color] = None
    family: Optional[str] = None


@dataclass
class FontChoice:
    fontname: str
    fontbuffer: Optional[bytes]
    size: float
    color: Color
    used_fallback: bool


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


_SERIF_HINTS = ('times', 'georgia', 'garamond', 'serif', 'cambria', 'book')
_BASE14_SANS = {(False, False): 'helv', (False, True): 'heit', (True, False): 'hebo', (True, True): 'hebi'}
_BASE14_SERIF = {(False, False): 'tiro', (False, True): 'tiit', (True, False): 'tibo', (True, True): 'tibi'}


def _normalize_family(name: str) -> dict:
    base = re.sub(r'^[A-Z]{6}\+', '', name)
    lowered = base.lower()
    bold = 'bold' in lowered
    italic = 'italic' in lowered or 'oblique' in lowered
    root = re.sub(r'(bold|italic|oblique|regular|mt|ps)', '', lowered)
    root = re.sub(r'[^a-z0-9]', '', root)
    return {'root': root, 'bold': bold, 'italic': italic}


def _embedded_font_buffer(doc: fitz.Document, page: fitz.Page, family_hint: Optional[str],
                           bold: bool, italic: bool) -> Tuple[Optional[str], Optional[bytes]]:
    if not family_hint:
        return None, None
    target = _normalize_family(family_hint)['root']
    for xref, _ext, _ftype, basefont, name, _encoding in page.get_fonts():
        for candidate in (basefont, name):
            norm = _normalize_family(candidate)
            if norm['root'] != target or norm['bold'] != bold or norm['italic'] != italic:
                continue
            try:
                info = doc.extract_font(xref)
            except Exception:
                continue
            buffer = info[-1] if info else None
            if buffer:
                return f'EF{xref}', buffer
    return None, None


def resolve_font(doc: fitz.Document, page: fitz.Page, span: Optional[TextSpan],
                  override: Optional[FormatOverride]) -> FontChoice:
    override = override or FormatOverride()
    bold = override.bold if override.bold is not None else (span.bold if span else False)
    italic = override.italic if override.italic is not None else (span.italic if span else False)
    size = override.size if override.size is not None else (span.size if span else 12.0)
    color = override.color if override.color is not None else (span.color if span else (0.0, 0.0, 0.0))
    family_hint = override.family if override.family else (span.font_name if span else None)

    fontname, fontbuffer = _embedded_font_buffer(doc, page, family_hint, bold, italic)
    if fontbuffer:
        return FontChoice(fontname, fontbuffer, size, color, used_fallback=False)

    if span is not None and not override.family:
        serifed = span.serifed
    else:
        serifed = any(hint in (family_hint or '').lower() for hint in _SERIF_HINTS)
    table = _BASE14_SERIF if serifed else _BASE14_SANS
    return FontChoice(table[(bold, italic)], None, size, color, used_fallback=True)
