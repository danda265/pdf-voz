from __future__ import annotations

import hashlib
import os

import fitz
import pytest

from pdf_editor import (FormatOverride, TextSpan, resolve_font, spans_for_page, replace_span_text,
                        _desenha_o_texto,
                        insert_free_text, PDFEditError, open_for_edit, save_copy, EditSession)
from pdf_editor_view import span_at_point
from utils import clean_text

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
    override = FormatOverride(family='FonteQueNaoExisteEmLugarNenhum')
    choice = resolve_font(doc, page, span, override, text='texto novo')
    doc.close()
    # Sem fonte embutida nem instalada com esse nome, sobra o base14 — e o usuario
    # precisa ser avisado de que o desenho da letra e so aproximado.
    assert choice.used_fallback is True
    assert choice.fontbuffer is None
    assert choice.fontname == 'helv'   # sem serifa, sem negrito, sem italico


def test_resolve_font_uses_real_system_font_when_family_is_installed(sample_pdf):
    """Familia instalada no Windows tem de vir de verdade, sem cair no base14."""
    from pdf_editor import _fonte_do_sistema

    if _fonte_do_sistema('Comic Sans MS', bold=False, italic=False) is None:
        pytest.skip('Comic Sans MS nao instalada neste sistema')
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = spans_for_page(page)[0]
    choice = resolve_font(doc, page, span, FormatOverride(family='Comic Sans MS'), text='texto novo')
    doc.close()
    assert choice.used_fallback is False
    assert fitz.Font(fontbuffer=choice.fontbuffer).has_glyph(ord('a'))


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


def test_spans_for_page_on_blank_page_returns_empty(blank_page_pdf):
    doc = fitz.open(str(blank_page_pdf))
    spans = spans_for_page(doc[0])
    doc.close()
    assert spans == []


def test_span_at_point_on_blank_page_finds_nothing(blank_page_pdf):
    doc = fitz.open(str(blank_page_pdf))
    spans = spans_for_page(doc[0])
    doc.close()
    assert span_at_point(spans, (100, 100)) is None


def test_spans_for_page_reads_each_page_of_multipage(multipage_pdf):
    doc = fitz.open(str(multipage_pdf))
    assert doc.page_count == 3
    textos = [' '.join(s.text for s in spans_for_page(doc[i])) for i in range(3)]
    doc.close()
    assert 'Pagina numero 1' in textos[0]
    assert 'Pagina numero 2' in textos[1]
    assert 'Pagina numero 3' in textos[2]


def test_save_copy_does_not_overwrite_an_existing_copy(sample_pdf):
    """Editar o mesmo PDF duas vezes nao pode sobrescrever a copia anterior."""
    primeira = sample_pdf.with_name(f'{sample_pdf.stem}_editado{sample_pdf.suffix}')
    primeira.write_bytes(b'copia anterior do usuario')
    conteudo_anterior = primeira.read_bytes()

    doc = fitz.open(str(sample_pdf))
    alvo = save_copy(doc, str(sample_pdf))
    doc.close()

    assert alvo != primeira
    assert alvo.name == f'{sample_pdf.stem}_editado_2{sample_pdf.suffix}'
    assert alvo.exists()
    assert primeira.read_bytes() == conteudo_anterior


def test_replace_span_text_keeps_original_when_font_resolution_fails(sample_pdf, monkeypatch):
    """Falha ao resolver a fonte nao pode apagar o texto original: a operacao aborta intacta."""
    import pdf_editor

    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')

    def falha(*_args, **_kwargs):
        raise RuntimeError('falha simulada ao resolver fonte')

    monkeypatch.setattr(pdf_editor, 'resolve_font', falha)
    with pytest.raises(RuntimeError):
        replace_span_text(doc, page, span, 'Texto novo')

    texto = page.get_text()
    doc.close()
    assert 'Ola mundo' in texto
    assert 'Segunda linha de teste' in texto


def test_replace_span_text_flags_overflow_when_new_text_is_wider(sample_pdf):
    """Texto novo mais largo que o trecho original e sinalizado (mas nao alterado)."""
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    choice = replace_span_text(doc, page, span, 'Um texto substancialmente mais longo que o original')
    texto = page.get_text()
    doc.close()
    assert choice.overflowed is True
    assert 'Um texto substancialmente mais longo que o original' in texto   # nada foi truncado


def test_replace_span_text_does_not_flag_overflow_when_new_text_fits(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    choice = replace_span_text(doc, page, span, 'Oi')
    doc.close()
    assert choice.overflowed is False


def test_replace_span_text_avoids_subset_font_that_cannot_draw_the_text(subset_font_pdf):
    """Fonte embutida como subset sem cmap nao pode ser reusada: sairiam caixinhas."""
    doc = fitz.open(str(subset_font_pdf))
    page = doc[0]
    span = spans_for_page(page)[0]
    choice = replace_span_text(doc, page, span, 'texto novo legivel')
    texto = page.get_text()
    doc.close()
    # O subset quebrado nao pode ser usado; o que entrar no lugar tem de saber
    # desenhar as letras (senao o usuario ve caixinhas).
    assert choice.fontbuffer is None or _desenha_o_texto(choice.fontbuffer, 'texto novo legivel')
    # clean_text normaliza o espaço não-separável que fontes reais gravam no lugar do espaço
    assert 'texto novo legivel' in clean_text(texto)


def test_desenha_o_texto_rejects_subset_without_usable_cmap(subset_font_pdf):
    from pdf_editor import _desenha_o_texto, _embedded_font_buffer

    doc = fitz.open(str(subset_font_pdf))
    page = doc[0]
    span = spans_for_page(page)[0]
    _name, buf = _embedded_font_buffer(doc, page, span.font_name, span.bold, span.italic)
    doc.close()
    assert buf is not None                        # a fonte embutida É encontrada...
    assert _desenha_o_texto(buf, 'abc') is False   # ...mas não consegue desenhar o texto


@pytest.mark.parametrize('bruto, esperado', [
    ('ABCDEF+Calibri-Bold', 'Calibri'),
    ('Times New Roman Regular', 'Times New Roman'),
    ('ArialMT', 'Arial'),
    ('Calibri,Bold', 'Calibri'),
    ('Verdana', 'Verdana'),
])
def test_familia_legivel_limpa_o_nome_bruto_do_pdf(bruto, esperado):
    from pdf_editor import familia_legivel
    assert familia_legivel(bruto) == esperado


def test_fonte_do_sistema_carrega_arquivo_real_do_windows():
    from pdf_editor import _fonte_do_sistema

    achado = _fonte_do_sistema('Arial', bold=False, italic=False)
    if achado is None:
        pytest.skip('Arial nao instalada neste sistema')
    nome, dados = achado
    assert nome.startswith('SYS')
    assert len(dados) > 1000
    assert fitz.Font(fontbuffer=dados).has_glyph(ord('a'))


def test_resolve_font_prefers_system_font_over_base14_when_family_is_chosen(sample_pdf):
    """Escolher 'Verdana' na lista tem de entregar Verdana de verdade, nao Helvetica."""
    from pdf_editor import _fonte_do_sistema

    if _fonte_do_sistema('Verdana', bold=False, italic=False) is None:
        pytest.skip('Verdana nao instalada neste sistema')
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = spans_for_page(page)[0]
    choice = resolve_font(doc, page, span, FormatOverride(family='Verdana'), text='texto novo')
    doc.close()
    assert choice.used_fallback is False
    assert choice.fontbuffer is not None
    assert choice.fontname.startswith('SYS')


def test_clean_text_normaliza_espaco_nao_separavel():
    """Fontes reais gravam \xa0 no lugar do espaco; a leitura em voz nao pode engasgar nisso."""
    assert clean_text('texto\xa0com\xa0espacos') == 'texto com espacos'
