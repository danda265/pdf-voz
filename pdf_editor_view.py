from __future__ import annotations

from typing import List, Optional, Tuple

import fitz
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog, QFontComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from pdf_editor import FormatOverride, TextSpan, familia_legivel

DEFAULT_ZOOM = 1.5


def span_at_point(spans: List[TextSpan], point: Tuple[float, float]) -> Optional[TextSpan]:
    x, y = point
    for span in spans:
        x0, y0, x1, y1 = span.bbox
        if x0 <= x <= x1 and y0 <= y <= y1:
            return span
    return None


# Quantos pixels o mouse precisa andar para virar arrasto em vez de clique. Abaixo disso
# o movimento e tremor de mao, nao intencao de mover o texto.
LIMIAR_ARRASTO = 5


class PageCanvas(QLabel):
    span_clicked = pyqtSignal(object)             # TextSpan
    free_area_clicked = pyqtSignal(float, float)   # ponto em coordenadas do documento (pontos PDF)
    span_moved = pyqtSignal(object, float, float)  # TextSpan, dx, dy (em pontos do PDF)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.zoom = DEFAULT_ZOOM
        self.spans: List[TextSpan] = []
        self.add_mode = False
        self._span_pressionado: Optional[TextSpan] = None
        self._pos_inicial = None
        self._arrastando = False

    def show_page(self, page: fitz.Page, spans: List[TextSpan]) -> None:
        self.spans = spans
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        self.setPixmap(QPixmap.fromImage(image.copy()))
        self.setFixedSize(pix.width, pix.height)
        self._cancelar_arrasto()

    def set_add_mode(self, enabled: bool) -> None:
        self.add_mode = enabled
        self._cancelar_arrasto()

    def _cancelar_arrasto(self) -> None:
        self._span_pressionado = None
        self._pos_inicial = None
        self._arrastando = False
        self.unsetCursor()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        doc_x = event.position().x() / self.zoom
        doc_y = event.position().y() / self.zoom
        if self.add_mode:
            self.free_area_clicked.emit(doc_x, doc_y)
            return
        # O clique so vira edicao ou arrasto no release: ate la nao da para saber qual dos
        # dois o usuario quis.
        self._span_pressionado = span_at_point(self.spans, (doc_x, doc_y))
        self._pos_inicial = event.position()
        self._arrastando = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._span_pressionado is None or self._pos_inicial is None:
            return
        percorrido = (event.position() - self._pos_inicial).manhattanLength()
        if not self._arrastando and percorrido > LIMIAR_ARRASTO:
            self._arrastando = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._span_pressionado is None:
            return
        span, inicial, arrastando = self._span_pressionado, self._pos_inicial, self._arrastando
        self._cancelar_arrasto()
        if not arrastando:
            self.span_clicked.emit(span)
            return
        delta = event.position() - inicial
        self.span_moved.emit(span, delta.x() / self.zoom, delta.y() / self.zoom)


class PageScrollArea(QScrollArea):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.canvas = PageCanvas()
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)


PASSO_SETA = 2.0   # pontos do PDF por clique nas setas (~0,7 mm)


class SpanEditPopup(QWidget):
    # span (ou None), texto novo, FormatOverride, deslocamento (dx, dy) em pontos do PDF
    confirmed = pyqtSignal(object, str, object, object)
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Popup)
        self._span: Optional[TextSpan] = None
        self._color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._family_touched = False   # o usuário escolheu outra fonte nesta edição?
        self._deslocamento = [0.0, 0.0]
        self.largura_pagina = 0.0      # preenchida pela janela ao trocar de página
        self._build_ui()

    def _build_ui(self) -> None:
        self.setMinimumWidth(560)
        # Estilo próprio: a folha de estilo da janela principal zera a seta do combo
        # (::drop-down sem imagem), deixando o seletor de fonte sem cara de lista.
        self.setStyleSheet("""
            QWidget { background:#FFFFFF; color:#0F172A; }
            QComboBox, QPlainTextEdit, QSpinBox {
                background:#FFFFFF; color:#0F172A;
                border:1.5px solid #CBD5E1; border-radius:6px; padding:5px 8px; min-height:28px;
            }
            QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:center right;
                                   width:20px; border:none; }
            QComboBox::down-arrow { image:none; width:0; height:0; margin-right:7px;
                                    border-left:5px solid transparent;
                                    border-right:5px solid transparent;
                                    border-top:6px solid #475569; }
            QComboBox QAbstractItemView { background:#FFFFFF; color:#0F172A;
                                          selection-background-color:#3B82F6; selection-color:#FFFFFF; }
            QLabel { color:#475569; font-size:12px; }
            #FonteOrigem, #Dica, #Deslocamento { color:#64748B; font-size:11px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Multi-linha: Enter quebra a linha (o texto desce), Ctrl+Enter confirma. Um campo
        # de uma linha so impediria quebrar o texto, que e justamente o que se precisa
        # quando a substituicao nao cabe na largura original.
        self.text_input = QPlainTextEdit()
        self.text_input.setFixedHeight(74)
        self.text_input.setTabChangesFocus(True)
        layout.addWidget(self.text_input)

        self.dica_lbl = QLabel('Enter quebra a linha · Ctrl+Enter confirma')
        self.dica_lbl.setObjectName('Dica')
        layout.addWidget(self.dica_lbl)

        toolbar = QHBoxLayout()
        self.bold_btn = QToolButton()
        self.bold_btn.setText('N')
        self.bold_btn.setToolTip('Negrito')
        self.bold_btn.setCheckable(True)
        self.italic_btn = QToolButton()
        self.italic_btn.setText('I')
        self.italic_btn.setToolTip('Itálico')
        self.italic_btn.setCheckable(True)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 96)
        self.size_spin.setValue(12)
        self.size_spin.setToolTip('Tamanho da fonte')
        self.font_combo = QFontComboBox()
        # Não-editável: clicar em qualquer ponto abre a lista de fontes. Editável, o
        # campo parecia uma caixa de texto comum e a lista ficava escondida.
        self.font_combo.setEditable(False)
        self.font_combo.setMinimumWidth(190)
        self.font_combo.setToolTip('Fonte — clique para ver a lista completa')
        self.font_combo.currentFontChanged.connect(self._on_family_changed)
        self.color_btn = QPushButton('Cor')
        self.color_btn.clicked.connect(self._pick_color)
        toolbar.addWidget(self.bold_btn)
        toolbar.addWidget(self.italic_btn)
        toolbar.addWidget(self.size_spin)
        toolbar.addWidget(QLabel('Fonte'))
        toolbar.addWidget(self.font_combo, 1)
        toolbar.addWidget(self.color_btn)
        layout.addLayout(toolbar)

        # Setas de posição: ajuste fino sem depender da mão firme no arrasto.
        posicao = QHBoxLayout()
        posicao.addWidget(QLabel('Posição'))
        for texto, dica, dx, dy in (
            ('←', 'Mover para a esquerda', -PASSO_SETA, 0.0),
            ('→', 'Mover para a direita', PASSO_SETA, 0.0),
            ('↑', 'Mover para cima', 0.0, -PASSO_SETA),
            ('↓', 'Mover para baixo', 0.0, PASSO_SETA),
        ):
            botao = QToolButton()
            botao.setText(texto)
            botao.setToolTip(dica + ' (segure para repetir)')
            botao.setAutoRepeat(True)
            botao.clicked.connect(lambda _=False, ex=dx, ey=dy: self._nudge(ex, ey))
            posicao.addWidget(botao)
        self.centralizar_btn = QPushButton('Centralizar na página')
        self.centralizar_btn.setToolTip('Coloca o trecho no centro horizontal da página')
        self.centralizar_btn.clicked.connect(self._centralizar)
        posicao.addWidget(self.centralizar_btn)
        self.reset_pos_btn = QPushButton('Voltar')
        self.reset_pos_btn.setToolTip('Desfaz o deslocamento e volta à posição original')
        self.reset_pos_btn.clicked.connect(self._reset_posicao)
        posicao.addWidget(self.reset_pos_btn)
        posicao.addStretch(1)
        self.deslocamento_lbl = QLabel('')
        self.deslocamento_lbl.setObjectName('Deslocamento')
        posicao.addWidget(self.deslocamento_lbl)
        layout.addLayout(posicao)

        # Mostra a fonte que o PDF declara para o trecho — sem isso não há como saber
        # qual escolher na lista quando o casamento automático não acerta.
        self.origem_lbl = QLabel('')
        self.origem_lbl.setObjectName('FonteOrigem')
        layout.addWidget(self.origem_lbl)

        buttons = QHBoxLayout()
        ok_btn = QPushButton('OK')
        ok_btn.clicked.connect(self._confirm)
        cancel_btn = QPushButton('Cancelar')
        cancel_btn.clicked.connect(self._cancel)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def open_for_span(self, span: TextSpan, global_pos, deslocamento=(0.0, 0.0)) -> None:
        """`deslocamento` chega preenchido quando o popup abre depois de um arrasto, para
        o usuário poder ajustar fino nas setas antes de confirmar."""
        self._span = span
        self._deslocamento = [float(deslocamento[0]), float(deslocamento[1])]
        self._atualizar_deslocamento_lbl()
        self.centralizar_btn.setEnabled(True)
        self.text_input.setPlainText(span.text)
        self.bold_btn.setChecked(span.bold)
        self.italic_btn.setChecked(span.italic)
        self.size_spin.setValue(int(span.size))
        familia = familia_legivel(span.font_name)
        # setCurrentFont dispara currentFontChanged; bloquear evita marcar como
        # "usuário trocou a fonte" o que é só o preenchimento inicial do popup.
        self.font_combo.blockSignals(True)
        self.font_combo.setCurrentFont(QFont(familia))
        self.font_combo.blockSignals(False)
        self._family_touched = False
        reconhecida = self.font_combo.currentFont().family().lower() == familia.lower()
        self.origem_lbl.setText(
            f'Fonte no PDF: {familia}'
            if reconhecida else
            f'Fonte no PDF: {familia} — não está instalada; escolha a mais parecida na lista'
        )
        self._color = span.color
        self.move(global_pos)
        self.show()
        self.text_input.setFocus()
        self.text_input.selectAll()

    def open_for_new_text(self, global_pos) -> None:
        self._span = None
        self._deslocamento = [0.0, 0.0]
        self._atualizar_deslocamento_lbl()
        # Texto novo já é colocado onde o usuário clicou; mover/centralizar não se aplica.
        self.centralizar_btn.setEnabled(False)
        self.text_input.clear()
        self.bold_btn.setChecked(False)
        self.italic_btn.setChecked(False)
        self.size_spin.setValue(12)
        self._family_touched = False
        self.origem_lbl.setText('Texto novo — escolha a fonte na lista')
        self._color = (0.0, 0.0, 0.0)
        self.move(global_pos)
        self.show()
        self.text_input.setFocus()

    # ── Posição ───────────────────────────────────────────────────────────────

    def _nudge(self, dx: float, dy: float) -> None:
        self._deslocamento[0] += dx
        self._deslocamento[1] += dy
        self._atualizar_deslocamento_lbl()

    def _centralizar(self) -> None:
        """Centraliza o trecho na largura da página, virando deslocamento horizontal."""
        if self._span is None or self.largura_pagina <= 0:
            return
        x0, _, x1, _ = self._span.bbox
        destino_x = (self.largura_pagina - (x1 - x0)) / 2
        self._deslocamento[0] = destino_x - x0
        self._atualizar_deslocamento_lbl()

    def _reset_posicao(self) -> None:
        self._deslocamento = [0.0, 0.0]
        self._atualizar_deslocamento_lbl()

    def _atualizar_deslocamento_lbl(self) -> None:
        dx, dy = self._deslocamento
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            self.deslocamento_lbl.setText('na posição original')
        else:
            self.deslocamento_lbl.setText(f'deslocado {dx:+.0f}, {dy:+.0f} pt')

    def _on_family_changed(self, _font) -> None:
        self._family_touched = True

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
            # Só manda família quando o usuário trocou de fonte de propósito. O nome
            # que o PDF traz costuma vir com prefixo de subset ("ABCDEF+TimesNewRoman"),
            # que o QFontComboBox resolve para uma família genérica — mandá-lo sempre
            # impediria o motor de reencontrar e reutilizar a fonte embutida original.
            family=self.font_combo.currentFont().family() if self._family_touched else None,
        )
        self.confirmed.emit(self._span, self.text_input.toPlainText(), override,
                            tuple(self._deslocamento))
        self.hide()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.hide()

    def keyPressEvent(self, event) -> None:
        """Ctrl+Enter confirma. Enter sozinho fica com o campo de texto, para quebrar linha."""
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._confirm()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)
