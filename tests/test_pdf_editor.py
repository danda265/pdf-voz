from __future__ import annotations

import os

import fitz
import pytest

from pdf_editor import FormatOverride, TextSpan, resolve_font, spans_for_page

ARIAL_PATH = r'C:\Windows\Fonts\arial.ttf'


@pytest.fixture
def embedded_font_pdf(tmp_path):
    if not os.path.exists(ARIAL_PATH):
        pytest.skip('Arial nao encontrada em C:\\Windows\\Fonts')
    path = tmp_path / 'embedded.pdf'
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_font(fontname='ArialCustom', fontfile=ARIAL_PATH)
    page.insert_text((72, 100), 'Texto com fonte embutida', fontsize=14, fontname='ArialCustom', color=(0, 0, 0))
    doc.save(str(path))
    doc.close()
    return path


def test_spans_for_page_extracts_text_and_position(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    spans = spans_for_page(doc[0])
    doc.close()
    texts = [s.text.strip() for s in spans]
    assert 'Ola mundo' in texts
    assert 'Segunda linha de teste' in texts
    first = next(s for s in spans if s.text.strip() == 'Ola mundo')
    assert first.size == 14.0
    assert first.bold is False
    assert first.italic is False


def test_resolve_font_reuses_embedded_font_when_available(embedded_font_pdf):
    doc = fitz.open(str(embedded_font_pdf))
    page = doc[0]
    span = spans_for_page(page)[0]
    choice = resolve_font(doc, page, span, override=None)
    doc.close()
    assert choice.used_fallback is False
    assert choice.fontbuffer


def test_resolve_font_falls_back_when_family_not_embedded(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = spans_for_page(page)[0]
    override = FormatOverride(family='Comic Sans MS')
    choice = resolve_font(doc, page, span, override)
    doc.close()
    assert choice.used_fallback is True
    assert choice.fontname in ('helv', 'heit', 'hebo', 'hebi', 'tiro', 'tibo', 'tiit', 'tibi')


def test_resolve_font_fallback_prefers_span_serifed_over_name_heuristic(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = TextSpan(
        text='Texto', bbox=(0, 0, 10, 10), origin=(0, 0), font_name='Palatino',
        size=12.0, color=(0, 0, 0), bold=False, italic=False, serifed=True,
    )
    choice = resolve_font(doc, page, span, override=None)
    doc.close()
    assert choice.fontname in ('tiro', 'tibo', 'tiit', 'tibi')
