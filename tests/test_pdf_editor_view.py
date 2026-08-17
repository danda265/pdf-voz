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

    emitted_span, emitted_text, override, deslocamento = blocker.args
    assert emitted_span is span
    assert emitted_text == 'Texto editado'
    assert isinstance(override, FormatOverride)
    assert override.bold is True
    assert override.italic is False
    assert override.size == 20.0
    assert deslocamento == (0.0, 0.0)   # sem mexer nas setas, fica na posição original


def test_texto_multilinha_e_preservado_no_confirm(qtbot):
    """Enter no campo tem de virar quebra de linha real no texto emitido."""
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_span(_make_span(), popup.pos())
    popup.text_input.setPlainText('primeira linha\nsegunda linha')

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()

    assert blocker.args[1] == 'primeira linha\nsegunda linha'


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

    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    span = _make_span()
    canvas.spans = [span]
    canvas.zoom = 2.0

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

    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.spans = [_make_span()]
    canvas.zoom = 2.0

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
