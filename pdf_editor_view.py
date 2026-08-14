from __future__ import annotations

from typing import List, Optional, Tuple

import fitz
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog, QFontComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from pdf_editor import FormatOverride, TextSpan

DEFAULT_ZOOM = 1.5


def span_at_point(spans: List[TextSpan], point: Tuple[float, float]) -> Optional[TextSpan]:
    x, y = point
    for span in spans:
        x0, y0, x1, y1 = span.bbox
        if x0 <= x <= x1 and y0 <= y <= y1:
            return span
    return None


class PageCanvas(QLabel):
    span_clicked = pyqtSignal(object)             # TextSpan
    free_area_clicked = pyqtSignal(float, float)   # ponto em coordenadas do documento (pontos PDF)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.zoom = DEFAULT_ZOOM
        self.spans: List[TextSpan] = []
        self.add_mode = False

    def show_page(self, page: fitz.Page, spans: List[TextSpan]) -> None:
        self.spans = spans
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        self.setPixmap(QPixmap.fromImage(image.copy()))
        self.setFixedSize(pix.width, pix.height)

    def set_add_mode(self, enabled: bool) -> None:
        self.add_mode = enabled

    def mousePressEvent(self, event: QMouseEvent) -> None:
        doc_x = event.position().x() / self.zoom
        doc_y = event.position().y() / self.zoom
        if self.add_mode:
            self.free_area_clicked.emit(doc_x, doc_y)
            return
        span = span_at_point(self.spans, (doc_x, doc_y))
        if span:
            self.span_clicked.emit(span)


class PageScrollArea(QScrollArea):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.canvas = PageCanvas()
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)


class SpanEditPopup(QWidget):
    confirmed = pyqtSignal(object, str, object)   # span (ou None), texto novo, FormatOverride
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Popup)
        self._span: Optional[TextSpan] = None
        self._color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.text_input = QLineEdit()
        self.text_input.returnPressed.connect(self._confirm)
        layout.addWidget(self.text_input)

        toolbar = QHBoxLayout()
        self.bold_btn = QToolButton()
        self.bold_btn.setText('N')
        self.bold_btn.setCheckable(True)
        self.italic_btn = QToolButton()
        self.italic_btn.setText('I')
        self.italic_btn.setCheckable(True)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 96)
        self.size_spin.setValue(12)
        self.font_combo = QFontComboBox()
        self.color_btn = QPushButton('Cor')
        self.color_btn.clicked.connect(self._pick_color)
        toolbar.addWidget(self.bold_btn)
        toolbar.addWidget(self.italic_btn)
        toolbar.addWidget(self.size_spin)
        toolbar.addWidget(self.font_combo)
        toolbar.addWidget(self.color_btn)
        layout.addLayout(toolbar)

        buttons = QHBoxLayout()
        ok_btn = QPushButton('OK')
        ok_btn.clicked.connect(self._confirm)
        cancel_btn = QPushButton('Cancelar')
        cancel_btn.clicked.connect(self._cancel)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def open_for_span(self, span: TextSpan, global_pos) -> None:
        self._span = span
        self.text_input.setText(span.text)
        self.bold_btn.setChecked(span.bold)
        self.italic_btn.setChecked(span.italic)
        self.size_spin.setValue(int(span.size))
        self.font_combo.setCurrentFont(QFont(span.font_name))
        self._color = span.color
        self.move(global_pos)
        self.show()
        self.text_input.setFocus()
        self.text_input.selectAll()

    def open_for_new_text(self, global_pos) -> None:
        self._span = None
        self.text_input.clear()
        self.bold_btn.setChecked(False)
        self.italic_btn.setChecked(False)
        self.size_spin.setValue(12)
        self._color = (0.0, 0.0, 0.0)
        self.move(global_pos)
        self.show()
        self.text_input.setFocus()

    def _pick_color(self) -> None:
        r, g, b = (int(c * 255) for c in self._color)
        chosen = QColorDialog.getColor(QColor(r, g, b), self)
        if chosen.isValid():
            self._color = (chosen.redF(), chosen.greenF(), chosen.blueF())

    def _confirm(self) -> None:
        override = FormatOverride(
            bold=self.bold_btn.isChecked(),
            italic=self.italic_btn.isChecked(),
            size=float(self.size_spin.value()),
            color=self._color,
            family=self.font_combo.currentFont().family(),
        )
        self.confirmed.emit(self._span, self.text_input.text(), override)
        self.hide()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.hide()
