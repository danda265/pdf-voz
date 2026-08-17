from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
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


def replace_span_text(doc: fitz.Document, page: fitz.Page, span: TextSpan, new_text: str,
                      override: Optional[FormatOverride] = None) -> FontChoice:
    # A fonte e resolvida ANTES de redigir: resolver le fontes embutidas do documento e
    # pode falhar. Redigindo primeiro, uma falha aqui deixaria o span apagado sem
    # substituto — texto perdido. Falhando antes, a pagina fica intacta.
    choice = resolve_font(doc, page, span, override) if new_text else None
    page.add_redact_annot(fitz.Rect(span.bbox), fill=(1, 1, 1))
    page.apply_redactions()
    if not new_text:
        return FontChoice('', None, span.size, span.color, used_fallback=False)
    if choice.fontbuffer:
        page.insert_font(fontname=choice.fontname, fontbuffer=choice.fontbuffer)
    page.insert_text(span.origin, new_text, fontname=choice.fontname,
                     fontsize=choice.size, color=choice.color)
    return choice


def insert_free_text(doc: fitz.Document, page: fitz.Page, point: Tuple[float, float],
                      text: str, override: FormatOverride) -> FontChoice:
    choice = resolve_font(doc, page, None, override)
    if choice.fontbuffer:
        page.insert_font(fontname=choice.fontname, fontbuffer=choice.fontbuffer)
    page.insert_text(point, text, fontname=choice.fontname, fontsize=choice.size, color=choice.color)
    return choice


class PDFEditError(Exception):
    pass


def open_for_edit(path: str) -> fitz.Document:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise PDFEditError(f'Nao foi possivel abrir o PDF: {exc}') from exc
    if doc.is_encrypted:
        doc.close()
        raise PDFEditError('Este PDF e protegido por senha e nao pode ser editado.')
    if not doc.permissions & fitz.PDF_PERM_MODIFY:
        doc.close()
        raise PDFEditError('Este PDF nao permite edicao (restricao de permissao do arquivo).')
    return doc


class EditSession:
    def __init__(self, doc: fitz.Document):
        self.doc = doc
        self._undo_stack: List[bytes] = []

    def snapshot(self) -> None:
        self._undo_stack.append(self.doc.tobytes())

    def discard_last_snapshot(self) -> None:
        if self._undo_stack:
            self._undo_stack.pop()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        data = self._undo_stack.pop()
        self.doc.close()
        self.doc = fitz.open(stream=data, filetype='pdf')
        return True


def save_copy(doc: fitz.Document, original_path: str) -> Path:
    original = Path(original_path)
    target = original.with_name(f'{original.stem}_editado{original.suffix}')
    counter = 2
    while target.exists():
        target = original.with_name(f'{original.stem}_editado_{counter}{original.suffix}')
        counter += 1
    doc.save(str(target))
    return target
