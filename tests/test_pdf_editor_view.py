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
    popup.text_input.setText('Texto editado')
    popup.bold_btn.setChecked(True)
    popup.size_spin.setValue(20)

    with qtbot.waitSignal(popup.confirmed, timeout=1000) as blocker:
        popup._confirm()

    emitted_span, emitted_text, override = blocker.args
    assert emitted_span is span
    assert emitted_text == 'Texto editado'
    assert isinstance(override, FormatOverride)
    assert override.bold is True
    assert override.italic is False
    assert override.size == 20.0


def test_cancel_emits_cancelled_without_confirmed(qtbot):
    popup = SpanEditPopup(None)
    qtbot.addWidget(popup)
    popup.open_for_new_text(popup.pos())

    with qtbot.waitSignal(popup.cancelled, timeout=1000):
        popup._cancel()
