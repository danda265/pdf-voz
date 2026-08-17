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
    # O base14 vai com o proprio arquivo da fonte, sob nome exclusivo ('PV...'): citar so
    # o nome faria a pagina reusar um recurso homonimo de metrica diferente.
    assert choice.fontname == 'PVhelv'   # sem serifa, sem negrito, sem italico
    assert choice.fontbuffer


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
    assert choice.fontname in ('PVtiro', 'PVtibo', 'PVtiit', 'PVtibi')


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


def test_replace_span_text_quebra_sozinho_texto_mais_longo(sample_pdf):
    """Texto longo demais quebra sozinho na largura da caixa, sem perder nada, e avisa
    que passou a ocupar mais linhas que o trecho original."""
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    longo = 'Um texto substancialmente mais longo que o original'
    choice = replace_span_text(doc, page, span, longo)
    texto = page.get_text()
    doc.close()
    assert choice.overflowed is True                  # ocupou linhas a mais
    assert ' '.join(texto.split()).count(longo) == 1   # quebrou, mas nao truncou nada


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


def test_replace_span_text_move_o_texto_pelo_deslocamento(sample_pdf):
    """Deslocamento reposiciona o texto novo sem deixar o antigo para tras."""
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    origem_x = span.origin[0]

    replace_span_text(doc, page, span, 'Movido', deslocamento=(100.0, 0.0))

    movido = next(s for s in spans_for_page(page) if s.text.strip() == 'Movido')
    texto = page.get_text()
    doc.close()
    assert abs(movido.origin[0] - (origem_x + 100.0)) < 1.0
    assert 'Ola mundo' not in texto          # o original nao ficou para tras
    assert 'Segunda linha de teste' in texto  # vizinho intacto


def test_replace_span_text_quebra_em_varias_linhas(sample_pdf):
    """'\n' no texto novo tem de virar linhas de verdade, descendo na pagina."""
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')

    replace_span_text(doc, page, span, 'primeira\nsegunda')

    spans = spans_for_page(page)
    doc.close()
    primeira = next(s for s in spans if s.text.strip() == 'primeira')
    segunda = next(s for s in spans if s.text.strip() == 'segunda')
    assert segunda.origin[1] > primeira.origin[1]        # a segunda desceu
    assert abs(segunda.origin[0] - primeira.origin[0]) < 1.0   # alinhadas a esquerda


def test_overflow_sinaliza_quando_ocupa_mais_linhas(sample_pdf):
    """Texto em varias linhas desce sobre a area de baixo — o usuario precisa saber."""
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')

    choice = replace_span_text(doc, page, span, 'curto\ncurto\ncurto')
    doc.close()
    assert choice.overflowed is True


def test_alinhamento_centro_centraliza_na_mancha_do_documento(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    from pdf_editor import area_de_conteudo
    mancha = area_de_conteudo(page)
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')

    replace_span_text(doc, page, span, 'Centro', FormatOverride(alinhamento='centro'))

    novo = next(s for s in spans_for_page(page) if s.text.strip() == 'Centro')
    doc.close()
    centro_texto = (novo.bbox[0] + novo.bbox[2]) / 2
    assert abs(centro_texto - (mancha.x0 + mancha.x1) / 2) < 2.0


def test_alinhamento_direita_encosta_na_borda_da_mancha(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    from pdf_editor import area_de_conteudo
    mancha = area_de_conteudo(page)
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')

    replace_span_text(doc, page, span, 'Direita', FormatOverride(alinhamento='direita'))

    novo = next(s for s in spans_for_page(page) if s.text.strip() == 'Direita')
    doc.close()
    assert abs(novo.bbox[2] - mancha.x1) < 3.0


def test_sem_alinhamento_o_texto_fica_exatamente_onde_estava(sample_pdf):
    """Manter a posicao original e o padrao — alinhar tem de ser escolha explicita."""
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    origem_antes = span.origin

    replace_span_text(doc, page, span, 'Trocado')

    novo = next(s for s in spans_for_page(page) if s.text.strip() == 'Trocado')
    doc.close()
    assert abs(novo.origin[0] - origem_antes[0]) < 0.5
    assert abs(novo.origin[1] - origem_antes[1]) < 0.5


def test_entrelinha_maior_afasta_as_linhas(sample_pdf):
    doc = fitz.open(str(sample_pdf))

    def distancia_entre_linhas(entrelinha):
        d = fitz.open(str(sample_pdf))
        pg = d[0]
        sp = next(s for s in spans_for_page(pg) if s.text.strip() == 'Ola mundo')
        replace_span_text(d, pg, sp, 'linha um\nlinha dois',
                          FormatOverride(entrelinha=entrelinha))
        spans = spans_for_page(pg)
        um = next(s for s in spans if s.text.strip() == 'linha um')
        dois = next(s for s in spans if s.text.strip() == 'linha dois')
        d.close()
        return dois.origin[1] - um.origin[1]

    doc.close()
    apertada, folgada = distancia_entre_linhas(1.0), distancia_entre_linhas(2.0)
    assert folgada > apertada * 1.5


def test_texto_que_nao_cabe_de_jeito_nenhum_levanta_erro_em_vez_de_sumir(sample_pdf):
    """insert_textbox nao escreve nada quando nao cabe. Com a redacao ja feita, aceitar
    isso apagaria o trecho — melhor erro explicito, que a janela trata restaurando."""
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')

    with pytest.raises(PDFEditError):
        replace_span_text(doc, page, span, 'palavra ' * 4000, FormatOverride(size=60.0))
    doc.close()


def test_replace_spans_text_preserva_a_formatacao_de_cada_linha(tmp_path):
    """Selecionar varias linhas nao pode uniformizar a formatacao delas: cada uma
    mantem tamanho e cor proprios quando o usuario nao mexe nesses controles."""
    from pdf_editor import replace_spans_text

    caminho = tmp_path / 'misto.pdf'
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((72, 100), 'TITULO GRANDE', fontsize=20, fontname='helv', color=(1, 0, 0))
    pg.insert_text((72, 140), 'corpo pequeno', fontsize=10, fontname='helv', color=(0, 0, 0))
    d.save(str(caminho)); d.close()

    doc = fitz.open(str(caminho))
    page = doc[0]
    spans = spans_for_page(page)
    grande = next(s for s in spans if s.text.strip() == 'TITULO GRANDE')
    pequeno = next(s for s in spans if s.text.strip() == 'corpo pequeno')

    # so alinhamento no override — nada de tamanho/cor
    replace_spans_text(doc, page, [grande, pequeno], ['TITULO NOVO', 'corpo novo'],
                       FormatOverride(alinhamento='centro'))

    novos = spans_for_page(page)
    n_grande = next(s for s in novos if s.text.strip() == 'TITULO NOVO')
    n_pequeno = next(s for s in novos if s.text.strip() == 'corpo novo')
    doc.close()
    assert abs(n_grande.size - 20.0) < 0.5     # cada um manteve o seu tamanho
    assert abs(n_pequeno.size - 10.0) < 0.5
    assert n_grande.color[0] > 0.9             # e a sua cor
    assert sum(n_pequeno.color) < 0.1


def test_replace_spans_text_aplica_a_todos_o_que_o_usuario_mudou(tmp_path):
    from pdf_editor import replace_spans_text

    caminho = tmp_path / 'misto2.pdf'
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((72, 100), 'primeira', fontsize=20, fontname='helv')
    pg.insert_text((72, 140), 'segunda', fontsize=10, fontname='helv')
    d.save(str(caminho)); d.close()

    doc = fitz.open(str(caminho))
    page = doc[0]
    spans = spans_for_page(page)
    alvos = [next(s for s in spans if s.text.strip() == t) for t in ('primeira', 'segunda')]

    replace_spans_text(doc, page, alvos, ['primeira', 'segunda'], FormatOverride(size=14.0))

    novos = spans_for_page(page)
    doc.close()
    for texto in ('primeira', 'segunda'):
        assert abs(next(s for s in novos if s.text.strip() == texto).size - 14.0) < 0.5
