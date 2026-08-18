from __future__ import annotations

from pdf_editor import FormatOverride, TextSpan
from pdf_editor_view import SpanEditPopup


def _make_span() -> TextSpan:
    return TextSpan(
        text='Ola mundo',
        bbox=(72.0, 100.0, 150.0, 114.0),
        origin=(72.0, 110.0),
        font_name='Helvetica',
        size=14.0,
        color=(0.0, 0.0, 0.0),
        bold=False,
        italic=False,
        serifed=False,
    )


def test_confirm_emits_edited_text_and_format_override(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    span = _make_span()

    popup.open_for_span(span, popup.pos())
    popup.text_input.setPlainText('Texto editado')
    popup.bold_btn.setChecked(True)
    popup.size_spin.setValue(20)

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()

    spans, textos, override, deslocamento = blocker.args
    assert spans == [span]
    assert textos == ['Texto editado']
    assert isinstance(override, FormatOverride)
    assert override.bold is True        # foi alterado (o span era False)
    assert override.size == 20.0        # foi alterado (o span era 14)
    assert override.italic is None      # NÃO foi tocado: o trecho mantém o que já tinha
    assert deslocamento == (0.0, 0.0)   # sem mexer nas setas, fica na posição original


def test_controles_nao_tocados_nao_entram_no_override(qtbot):
    """Base de tudo: o que o usuário não mexeu tem de sair None, senão editar vários
    trechos juntos uniformizaria a formatação de todos."""
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos())

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()

    override = blocker.args[2]
    assert override.bold is None
    assert override.italic is None
    assert override.size is None
    assert override.color is None
    assert override.family is None


def test_texto_multilinha_e_preservado_no_confirm(qtbot):
    """Enter no campo tem de virar quebra de linha real no texto emitido."""
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos())
    popup.text_input.setPlainText('primeira linha\nsegunda linha')

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()

    assert blocker.args[1] == ['primeira linha\nsegunda linha']


def test_setas_acumulam_deslocamento(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos())

    popup._nudge(2.0, 0.0)
    popup._nudge(2.0, 0.0)
    popup._nudge(0.0, -2.0)

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()

    assert blocker.args[3] == (4.0, -2.0)


def test_voltar_zera_o_deslocamento(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos(), deslocamento=(30.0, 12.0))

    popup._reset_posicao()

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()

    assert blocker.args[3] == (0.0, 0.0)


def test_alinhamento_vai_no_override_e_botoes_funcionam_como_radio(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos())

    popup._escolher_alinhamento('centro')
    assert popup.alinhamento_btns['centro'].isChecked() is True

    popup._escolher_alinhamento('direita')
    assert popup.alinhamento_btns['direita'].isChecked() is True
    assert popup.alinhamento_btns['centro'].isChecked() is False   # só um marcado

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()
    assert blocker.args[2].alinhamento == 'direita'


def test_entrelinha_escolhida_vai_no_override(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos())

    indice_dupla = popup.entrelinha_combo.findText('Dupla')
    popup.entrelinha_combo.setCurrentIndex(indice_dupla)

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()
    assert blocker.args[2].entrelinha == 2.0


def test_abrir_outro_trecho_zera_alinhamento_e_entrelinha(qtbot):
    """Estado de um trecho não pode vazar para a edição do trecho seguinte."""
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos())
    popup._escolher_alinhamento('justificado')
    popup.entrelinha_combo.setCurrentIndex(popup.entrelinha_combo.findText('Dupla'))

    popup.open_for_span(_make_span(), popup.pos())

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()
    assert blocker.args[2].alinhamento is None
    assert blocker.args[2].entrelinha is None


def test_arrasto_no_canvas_emite_span_moved_em_pontos_do_pdf(qtbot):
    """O canvas trabalha em pixels de tela; o sinal tem de sair em pontos do PDF."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from pdf_editor_view import PageCanvas

    span = _make_span()
    canvas = _canvas_pronto(qtbot, [span], zoom=2.0)

    def evento(tipo, x, y):
        return QMouseEvent(tipo, QPointF(x, y), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    # pressiona dentro do span (bbox 72..150 x 100..114, em pontos -> x2 na tela)
    canvas.mousePressEvent(evento(QMouseEvent.Type.MouseButtonPress, 200.0, 214.0))
    canvas.mouseMoveEvent(evento(QMouseEvent.Type.MouseMove, 240.0, 234.0))
    with qtbot.waitSignal(canvas.span_moved, timeout=1000) as blocker:
        canvas.mouseReleaseEvent(evento(QMouseEvent.Type.MouseButtonRelease, 240.0, 234.0))

    movido, dx, dy = blocker.args
    assert movido is span
    assert abs(dx - 20.0) < 0.01   # 40 px de tela / zoom 2.0
    assert abs(dy - 10.0) < 0.01


def test_clique_curto_nao_vira_arrasto(qtbot):
    """Tremor de mão abaixo do limiar tem de continuar sendo clique de edição."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from pdf_editor_view import PageCanvas

    canvas = _canvas_pronto(qtbot, [_make_span()], zoom=2.0)

    def evento(tipo, x, y):
        return QMouseEvent(tipo, QPointF(x, y), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    canvas.mousePressEvent(evento(QMouseEvent.Type.MouseButtonPress, 200.0, 214.0))
    canvas.mouseMoveEvent(evento(QMouseEvent.Type.MouseMove, 202.0, 215.0))
    with qtbot.waitSignal(canvas.span_clicked, timeout=1000):
        canvas.mouseReleaseEvent(evento(QMouseEvent.Type.MouseButtonRelease, 202.0, 215.0))


def test_cancel_emits_cancelled_without_confirmed(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_new_text(popup.pos())

    with qtbot.waitSignal(popup.cancelled, timeout=1000):
        popup._cancel()


def _span_em(y, texto='linha', x0=72.0, x1=200.0):
    from pdf_editor import TextSpan
    return TextSpan(text=texto, bbox=(x0, y, x1, y + 12.0), origin=(x0, y + 10.0),
                    font_name='Helvetica', size=12.0, color=(0.0, 0.0, 0.0),
                    bold=False, italic=False, serifed=False)


def _canvas_pronto(qtbot, spans, zoom=1.0, paginas=1):
    """Canvas montado como em uso (com documento de verdade), mas com trechos sintéticos
    de posição conhecida — o hit-test precisa do documento para saber onde cada página cai."""
    import fitz
    from pdf_editor_view import PageCanvas

    doc = fitz.open()
    for _ in range(paginas):
        doc.new_page(width=595, height=842)
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.zoom = zoom
    canvas.mostrar_documento(doc)
    canvas.spans = spans          # substitui os do documento vazio
    canvas._doc_de_teste = doc    # mantém vivo enquanto o canvas existir
    return canvas


def test_spans_na_area_pega_quem_encosta_e_ordena_de_cima_para_baixo():
    from pdf_editor_view import spans_na_area
    a, b, c = _span_em(100, 'a'), _span_em(140, 'b'), _span_em(300, 'c')

    escolhidos = spans_na_area([c, a, b], (60.0, 90.0, 250.0, 160.0))

    assert [s.text for s in escolhidos] == ['a', 'b']   # 'c' está fora, e veio ordenado


def test_spans_na_area_aceita_retangulo_desenhado_de_baixo_para_cima():
    """Arrastar de baixo para cima tem de selecionar igual."""
    from pdf_editor_view import spans_na_area
    a, b = _span_em(100, 'a'), _span_em(140, 'b')

    assert len(spans_na_area([a, b], (250.0, 160.0, 60.0, 90.0))) == 2


def test_selecao_por_retangulo_emite_spans_selected(qtbot):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from pdf_editor_view import PageCanvas

    canvas = _canvas_pronto(qtbot, [_span_em(100, 'a'), _span_em(140, 'b'), _span_em(400, 'longe')])

    def ev(tipo, x, y):
        return QMouseEvent(tipo, QPointF(x, y), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    # comeca numa area VAZIA (fora de qualquer span) e arrasta por cima de 'a' e 'b'
    canvas.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, 40.0, 90.0))
    canvas.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, 250.0, 160.0))
    with qtbot.waitSignal(canvas.spans_selected, timeout=1000) as blocker:
        canvas.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, 250.0, 160.0))

    assert [s.text for s in blocker.args[0]] == ['a', 'b']
    assert len(canvas.selecionados) == 2   # ficam destacados na tela


def test_edicao_de_varios_trechos_devolve_um_texto_por_trecho(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    spans = [_span_em(100, 'primeira'), _span_em(140, 'segunda')]

    popup.open_for_spans(spans, popup.pos())
    assert popup.text_input.toPlainText() == 'primeira\nsegunda'

    popup.text_input.setPlainText('PRIMEIRA\nSEGUNDA')
    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()

    assert blocker.args[0] == spans
    assert blocker.args[1] == ['PRIMEIRA', 'SEGUNDA']


def test_setas_pedem_previa_da_nova_posicao(qtbot):
    """Sem o aviso, o usuário só descobre onde o texto caiu depois de confirmar."""
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_span_em(100), popup.pos())

    with qtbot.waitSignal(popup.posicao_mudou, timeout=1000) as blocker:
        popup._nudge(2.0, 0.0)

    assert blocker.args[1] == 2.0
    assert blocker.args[2] == 0.0


def test_clique_no_vazio_adiciona_texto_ali(qtbot):
    """Clicar numa área em branco tem de abrir a caixa de texto novo naquele ponto,
    sem precisar ligar nenhum modo antes."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from pdf_editor_view import PageCanvas

    canvas = _canvas_pronto(qtbot, [_span_em(100, 'existente')], zoom=2.0)

    def ev(tipo, x, y):
        return QMouseEvent(tipo, QPointF(x, y), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    # clique seco (sem arrasto) bem longe de qualquer texto
    canvas.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, 600.0, 1200.0))
    with qtbot.waitSignal(canvas.free_area_clicked, timeout=1000) as blocker:
        canvas.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, 600.0, 1200.0))

    assert blocker.args[0] == 0                  # página 0
    assert abs(blocker.args[1] - 300.0) < 0.01   # 600 px / zoom 2.0
    assert abs(blocker.args[2] - 600.0) < 0.01


def test_arrasto_no_vazio_seleciona_em_vez_de_adicionar(qtbot):
    """O gesto de arrastar continua sendo seleção — não pode virar texto novo."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from pdf_editor_view import PageCanvas

    canvas = _canvas_pronto(qtbot, [_span_em(100, 'a'), _span_em(140, 'b')])
    adicionou = []
    canvas.free_area_clicked.connect(lambda pg, x, y: adicionou.append((pg, x, y)))

    def ev(tipo, x, y):
        return QMouseEvent(tipo, QPointF(x, y), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    canvas.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, 40.0, 90.0))
    canvas.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, 250.0, 160.0))
    with qtbot.waitSignal(canvas.spans_selected, timeout=1000):
        canvas.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, 250.0, 160.0))

    assert adicionou == [], 'arrasto não pode disparar adicionar texto'


def test_confirmar_apaga_o_fantasma_da_previa(qtbot):
    """Sem apagar, o fantasma fica desenhado por cima do texto recém-movido e parece
    que o trecho duplicou — foi exatamente o que apareceu em uso."""
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos(), deslocamento=(20.0, 5.0))

    avisos = []
    popup.posicao_mudou.connect(lambda spans, dx, dy: avisos.append((list(spans), dx, dy)))
    popup._confirm()

    assert avisos, 'não avisou nada ao confirmar'
    assert avisos[-1] == ([], 0.0, 0.0), 'último aviso tem de limpar a prévia'


def test_cancelar_tambem_apaga_o_fantasma(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos(), deslocamento=(20.0, 5.0))

    avisos = []
    popup.posicao_mudou.connect(lambda spans, dx, dy: avisos.append((list(spans), dx, dy)))
    popup._cancel()

    assert avisos[-1] == ([], 0.0, 0.0)


def test_redesenhar_a_pagina_nao_carrega_fantasma_antigo(qtbot, sample_pdf):
    """Rede de segurança: nenhum fantasma pode sobreviver a um redesenho da página."""
    import fitz
    from pdf_editor import spans_for_page
    from pdf_editor_view import PageCanvas

    from pdf_editor_view import PageCanvas
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    doc = fitz.open(str(sample_pdf))
    canvas.mostrar_documento(doc)
    canvas.previsualizar(spans_for_page(doc[0]), 30.0, 10.0)
    assert canvas._previa[0]

    canvas.recarregar_spans()
    assert canvas._previa == ([], 0.0, 0.0)
    doc.close()


def test_documento_continuo_empilha_todas_as_paginas(qtbot):
    """Rolar tem de percorrer o documento inteiro, não uma página por vez."""
    import fitz
    from pdf_editor_view import PageCanvas

    doc = fitz.open()
    for n in (1, 2, 3):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((72, 100), f'TOPO {n}', fontsize=14, fontname='helv')

    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.zoom = 1.5
    canvas.mostrar_documento(doc)

    assert len(canvas._tops) == 3
    assert canvas.height() > 842 * 1.5 * 2, 'não empilhou as páginas'
    assert sorted({s.pagina for s in canvas.spans}) == [0, 1, 2]
    doc.close()


def test_rolagem_mapeia_para_a_pagina_certa(qtbot):
    import fitz
    from pdf_editor_view import PageCanvas

    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.zoom = 1.5
    canvas.mostrar_documento(doc)
    altura = 842 * 1.5

    assert canvas.pagina_no_topo(0) == 0
    assert canvas.pagina_no_topo(altura - 10) == 0
    assert canvas.pagina_no_topo(altura + 20) == 1
    assert canvas.pagina_no_topo(altura * 2 + 50) == 2
    doc.close()


def test_coordenadas_vao_e_voltam_sem_perder_a_pagina(qtbot):
    """O clique precisa virar (página, x, y) do PDF e voltar ao mesmo pixel."""
    import fitz
    from pdf_editor_view import PageCanvas

    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.zoom = 1.5
    canvas.mostrar_documento(doc)

    px, py = canvas.ponto_na_tela(1, 72.0, 100.0)
    pagina, x, y = canvas.posicao_no_documento(px, py)
    doc.close()
    assert pagina == 1
    assert abs(x - 72.0) < 0.01 and abs(y - 100.0) < 0.01


def test_clique_na_pagina_de_baixo_acha_o_trecho_daquela_pagina(qtbot):
    """Com tudo empilhado, o hit-test precisa olhar só os trechos da página clicada."""
    import fitz
    from pdf_editor_view import PageCanvas, span_at_point

    doc = fitz.open()
    for n in (1, 2, 3):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((72, 100), f'TOPO {n}', fontsize=14, fontname='helv')
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.zoom = 1.5
    canvas.mostrar_documento(doc)

    alvo = next(s for s in canvas.spans if s.text.strip() == 'TOPO 3')
    mx, my = canvas.ponto_na_tela(alvo.pagina,
                                  (alvo.bbox[0] + alvo.bbox[2]) / 2,
                                  (alvo.bbox[1] + alvo.bbox[3]) / 2)
    pagina, dx, dy = canvas.posicao_no_documento(mx, my)
    achado = span_at_point([s for s in canvas.spans if s.pagina == pagina], (dx, dy))
    doc.close()
    assert pagina == 2
    assert achado is not None and achado.text.strip() == 'TOPO 3'
