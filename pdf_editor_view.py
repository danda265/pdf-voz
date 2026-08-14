from __future__ import annotations

from typing import List, Optional, Tuple

import fitz
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QLabel, QScrollArea, QWidget

from pdf_editor import TextSpan

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
