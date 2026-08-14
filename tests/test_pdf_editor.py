from __future__ import annotations

import hashlib
import os

import fitz
import pytest

from pdf_editor import (FormatOverride, TextSpan, resolve_font, spans_for_page, replace_span_text,
                        insert_free_text, PDFEditError, open_for_edit, save_copy, EditSession)
from pdf_editor_view import span_at_point

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


def test_replace_span_text_changes_only_target_span(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    replace_span_text(doc, page, span, 'Texto trocado')
    full_text = page.get_text()
    doc.close()
    assert 'Texto trocado' in full_text
    assert 'Ola mundo' not in full_text
    assert 'Segunda linha de teste' in full_text


def test_replace_span_text_with_empty_string_deletes(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    replace_span_text(doc, page, span, '')
    full_text = page.get_text()
    doc.close()
    assert 'Ola mundo' not in full_text
    assert 'Segunda linha de teste' in full_text


def test_insert_free_text_adds_without_touching_existing_spans(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    before = page.get_text()
    insert_free_text(doc, page, (72, 700), 'Texto novo', FormatOverride(size=12.0, color=(0, 0, 0)))
    after = page.get_text()
    doc.close()
    assert 'Texto novo' in after
    assert before.strip() in after


def test_open_for_edit_rejects_encrypted_pdf(tmp_path):
    path = tmp_path / 'protegido.pdf'
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='dono', user_pw='usuario')
    doc.close()
    with pytest.raises(PDFEditError):
        open_for_edit(str(path))


def test_open_for_edit_rejects_corrupted_file(tmp_path):
    path = tmp_path / 'corrompido.pdf'
    path.write_bytes(b'nao e um pdf de verdade')
    with pytest.raises(PDFEditError):
        open_for_edit(str(path))


def test_save_copy_never_overwrites_original(sample_pdf):
    original_bytes_before = sample_pdf.read_bytes()
    doc = open_for_edit(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    replace_span_text(doc, page, span, 'Editado')
    target = save_copy(doc, str(sample_pdf))
    doc.close()
    assert target != sample_pdf
    assert target.exists()
    assert hashlib.sha256(sample_pdf.read_bytes()).hexdigest() == hashlib.sha256(original_bytes_before).hexdigest()


def test_undo_reverts_last_edit(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    session = EditSession(doc)
    page = session.doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    session.snapshot()
    replace_span_text(session.doc, page, span, 'Texto trocado')
    assert 'Texto trocado' in session.doc[0].get_text()
    assert session.undo() is True
    assert 'Ola mundo' in session.doc[0].get_text()
    assert 'Texto trocado' not in session.doc[0].get_text()
    assert session.undo() is False
    session.doc.close()


def test_span_at_point_finds_span_containing_point(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    spans = spans_for_page(doc[0])
    doc.close()
    target = next(s for s in spans if s.text.strip() == 'Ola mundo')
    x0, y0, x1, y1 = target.bbox
    midpoint = ((x0 + x1) / 2, (y0 + y1) / 2)
    found = span_at_point(spans, midpoint)
    assert found is target


def test_span_at_point_returns_none_outside_any_span(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    spans = spans_for_page(doc[0])
    doc.close()
    assert span_at_point(spans, (10, 780)) is None
