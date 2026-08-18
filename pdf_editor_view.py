from __future__ import annotations

from typing import List, Optional, Tuple

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog, QComboBox, QFontComboBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton,
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


def spans_na_area(spans: List[TextSpan], area: Tuple[float, float, float, float]) -> List[TextSpan]:
    """Trechos que encostam no retangulo (coordenadas do documento), de cima para baixo.

    Encostar basta — exigir que o trecho caiba inteiro obrigaria o usuario a envolver as
    linhas com precisao de pixel."""
    ax0, ay0, ax1, ay1 = min(area[0], area[2]), min(area[1], area[3]), \
                         max(area[0], area[2]), max(area[1], area[3])
    dentro = [s for s in spans
              if s.bbox[0] <= ax1 and s.bbox[2] >= ax0
              and s.bbox[1] <= ay1 and s.bbox[3] >= ay0]
    return sorted(dentro, key=lambda s: (round(s.bbox[1], 1), s.bbox[0]))


class PageCanvas(QLabel):
    span_clicked = pyqtSignal(object)             # TextSpan
    free_area_clicked = pyqtSignal(float, float)   # ponto em coordenadas do documento (pontos PDF)
    span_moved = pyqtSignal(object, float, float)  # TextSpan, dx, dy (em pontos do PDF)
    spans_selected = pyqtSignal(list)              # varios TextSpan de uma vez

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.zoom = DEFAULT_ZOOM
        self.spans: List[TextSpan] = []
        self.selecionados: List[TextSpan] = []
        self._span_pressionado: Optional[TextSpan] = None
        self._pos_inicial = None
        self._pos_atual = None
        self._arrastando = False
        self._marcando = False   # desenhando o retangulo de selecao
        self._previa = ([], 0.0, 0.0)   # (spans, dx, dy) — para onde o texto vai

    def show_page(self, page: fitz.Page, spans: List[TextSpan]) -> None:
        self.spans = spans
        self.selecionados = []
        self._previa = ([], 0.0, 0.0)   # nenhum fantasma sobrevive a um redesenho
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        self.setPixmap(QPixmap.fromImage(image.copy()))
        self.setFixedSize(pix.width, pix.height)
        self._cancelar_arrasto()

    def destacar(self, spans: List[TextSpan]) -> None:
        self.selecionados = list(spans)
        self.update()

    def previsualizar(self, spans: List[TextSpan], dx: float, dy: float) -> None:
        """Mostra na página para onde o texto vai antes de confirmar."""
        self._previa = (list(spans), dx, dy)
        self.update()

    def _cancelar_arrasto(self) -> None:
        self._span_pressionado = None
        self._pos_inicial = None
        self._pos_atual = None
        self._arrastando = False
        self._marcando = False
        self.unsetCursor()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        doc_x = event.position().x() / self.zoom
        doc_y = event.position().y() / self.zoom
        # Quatro gestos, decididos no release porque so ali se sabe se houve arrasto:
        #   em cima de texto  — clique edita, arrasto move
        #   em area vazia     — clique adiciona texto ali, arrasto seleciona varios
        self._span_pressionado = span_at_point(self.spans, (doc_x, doc_y))
        self._marcando = self._span_pressionado is None
        self._pos_inicial = event.position()
        self._pos_atual = event.position()
        self._arrastando = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pos_inicial is None:
            return
        self._pos_atual = event.position()
        percorrido = (event.position() - self._pos_inicial).manhattanLength()
        if not self._arrastando and percorrido > LIMIAR_ARRASTO:
            self._arrastando = True
            if not self._marcando:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._marcando and self._arrastando:
            self.update()   # redesenha o retangulo em tempo real

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._pos_inicial is None:
            return
        span, inicial = self._span_pressionado, self._pos_inicial
        arrastando, marcando = self._arrastando, self._marcando
        fim = event.position()
        self._cancelar_arrasto()

        if marcando:
            if not arrastando:
                # clique seco no vazio: adiciona texto ali mesmo, sem precisar ligar modo
                self.free_area_clicked.emit(fim.x() / self.zoom, fim.y() / self.zoom)
                return
            area = (inicial.x() / self.zoom, inicial.y() / self.zoom,
                    fim.x() / self.zoom, fim.y() / self.zoom)
            escolhidos = spans_na_area(self.spans, area)
            if escolhidos:
                self.destacar(escolhidos)
                self.spans_selected.emit(escolhidos)
            return

        if span is None:
            return
        if not arrastando:
            self.span_clicked.emit(span)
            return
        delta = fim - inicial
        self.span_moved.emit(span, delta.x() / self.zoom, delta.y() / self.zoom)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        previa_spans, pdx, pdy = self._previa
        tem_previa = previa_spans and (abs(pdx) > 0.01 or abs(pdy) > 0.01)
        if not self.selecionados and not tem_previa and not (self._marcando and self._arrastando):
            return
        pintor = QPainter(self)
        for span in self.selecionados:
            x0, y0, x1, y1 = (v * self.zoom for v in span.bbox)
            pintor.fillRect(QRectF(x0, y0, x1 - x0, y1 - y0), QColor(59, 130, 246, 60))

        if tem_previa:
            # Fantasma na posição de destino: o retângulo de origem riscado e o texto
            # desenhado onde vai parar.
            pintor.setPen(QPen(QColor(148, 163, 184), 1, Qt.PenStyle.DotLine))
            for span in previa_spans:
                x0, y0, x1, y1 = (v * self.zoom for v in span.bbox)
                pintor.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
            pintor.setPen(QPen(QColor(217, 119, 6)))
            for span in previa_spans:
                fonte = QFont(familia_legivel(span.font_name))
                fonte.setPixelSize(max(1, int(span.size * self.zoom)))
                fonte.setBold(span.bold)
                fonte.setItalic(span.italic)
                pintor.setFont(fonte)
                pintor.drawText(
                    QPointF((span.origin[0] + pdx) * self.zoom,
                            (span.origin[1] + pdy) * self.zoom),
                    span.text,
                )

        if self._marcando and self._arrastando and self._pos_atual is not None:
            pintor.setPen(QPen(QColor(59, 130, 246), 1, Qt.PenStyle.DashLine))
            pintor.drawRect(QRectF(self._pos_inicial, self._pos_atual).normalized())
        pintor.end()


class PageScrollArea(QScrollArea):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.canvas = PageCanvas()
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)


PASSO_SETA = 2.0   # pontos do PDF por clique nas setas (~0,7 mm)


class SpanEditPopup(QWidget):
    # lista de TextSpan (ou None para texto novo), lista de textos, FormatOverride,
    # deslocamento (dx, dy) em pontos do PDF
    confirmed = pyqtSignal(object, object, object, object)
    cancelled = pyqtSignal()
    posicao_mudou = pyqtSignal(object, float, float)   # spans, dx, dy — para a prévia

    def __init__(self, parent: QWidget):
        # Janela de ferramenta, não popup: pode ser arrastada pela barra de título para
        # sair da frente do texto, e não se fecha sozinha ao clicar fora.
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle('Editar trecho')
        self._spans: List[TextSpan] = []
        self._color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._deslocamento = [0.0, 0.0]
        self._alinhamento = None
        # Estado dos controles quando o popup abriu. Comparar contra ele diz o que o
        # usuário mexeu de fato — e só isso entra no override, para cada trecho manter a
        # própria formatação no que ele não tocou.
        self._inicial = {}
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
        self.reset_pos_btn = QPushButton('Voltar')
        self.reset_pos_btn.setToolTip('Desfaz o deslocamento e volta à posição original')
        self.reset_pos_btn.clicked.connect(self._reset_posicao)
        posicao.addWidget(self.reset_pos_btn)
        posicao.addStretch(1)
        self.deslocamento_lbl = QLabel('')
        self.deslocamento_lbl.setObjectName('Deslocamento')
        posicao.addWidget(self.deslocamento_lbl)
        layout.addLayout(posicao)

        # Alinhamento e entrelinha — o equivalente ao grupo "Parágrafo" do Word.
        paragrafo = QHBoxLayout()
        paragrafo.addWidget(QLabel('Alinhar'))
        self.alinhamento_btns = {}
        for chave, rotulo, dica in (
            (None, '⌸', 'Manter onde está (padrão)'),
            ('esquerda', '⯇', 'Alinhar à esquerda da margem'),
            ('centro', '≡', 'Centralizar'),
            ('direita', '⯈', 'Alinhar à direita da margem'),
            ('justificado', '☰', 'Justificar (estica até as duas margens)'),
        ):
            botao = QToolButton()
            botao.setText(rotulo)
            botao.setToolTip(dica)
            botao.setCheckable(True)
            botao.clicked.connect(lambda _=False, c=chave: self._escolher_alinhamento(c))
            self.alinhamento_btns[chave] = botao
            paragrafo.addWidget(botao)

        paragrafo.addSpacing(10)
        paragrafo.addWidget(QLabel('Entrelinha'))
        self.entrelinha_combo = QComboBox()
        self.entrelinha_combo.setToolTip('Espaço entre as linhas do trecho')
        for rotulo, valor in (('Original', None), ('Simples', 1.0), ('1,5', 1.5), ('Dupla', 2.0)):
            self.entrelinha_combo.addItem(rotulo, valor)
        paragrafo.addWidget(self.entrelinha_combo)
        paragrafo.addStretch(1)
        layout.addLayout(paragrafo)

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
        self.open_for_spans([span], global_pos, deslocamento)

    def open_for_spans(self, spans: List[TextSpan], global_pos,
                       deslocamento=(0.0, 0.0)) -> None:
        """Abre para um ou vários trechos. Com vários, cada linha da caixa corresponde a
        um trecho, e os controles de formatação começam mostrando os do primeiro."""
        self._spans = list(spans)
        span = spans[0]
        self._deslocamento = [float(deslocamento[0]), float(deslocamento[1])]
        self._atualizar_deslocamento_lbl()
        self._escolher_alinhamento(None)
        self.entrelinha_combo.setCurrentIndex(0)
        self.text_input.setPlainText('\n'.join(s.text for s in spans))
        self.bold_btn.setChecked(span.bold)
        self.italic_btn.setChecked(span.italic)
        self.size_spin.setValue(int(span.size))
        familia = familia_legivel(span.font_name)
        self.font_combo.setCurrentFont(QFont(familia))
        reconhecida = self.font_combo.currentFont().family().lower() == familia.lower()
        self.origem_lbl.setText(
            f'Fonte no PDF: {familia}'
            if reconhecida else
            f'Fonte no PDF: {familia} — não está instalada; escolha a mais parecida na lista'
        )
        self._color = span.color
        formatos = {(s.size, s.bold, s.italic, s.color) for s in spans}
        if len(spans) > 1:
            self.dica_lbl.setText(
                f'{len(spans)} trechos · uma linha da caixa por trecho · Ctrl+Enter confirma'
                + (' · formatações diferentes: só muda o que você mexer' if len(formatos) > 1 else '')
            )
        else:
            self.dica_lbl.setText('Enter quebra a linha · Ctrl+Enter confirma')
        self._guardar_estado_inicial()
        self.move(global_pos)
        self.show()
        self._avisar_posicao()
        self.text_input.setFocus()
        self.text_input.selectAll()

    def open_for_new_text(self, global_pos) -> None:
        self._spans = []
        self._deslocamento = [0.0, 0.0]
        self._atualizar_deslocamento_lbl()
        # Texto novo já é colocado onde o usuário clicou; mover/centralizar não se aplica.
        self._escolher_alinhamento(None)
        self.entrelinha_combo.setCurrentIndex(0)
        self.text_input.clear()
        self.bold_btn.setChecked(False)
        self.italic_btn.setChecked(False)
        self.size_spin.setValue(12)
        self.origem_lbl.setText('Texto novo — escolha a fonte na lista')
        self.dica_lbl.setText('Enter quebra a linha · Ctrl+Enter confirma')
        self._color = (0.0, 0.0, 0.0)
        self._guardar_estado_inicial()
        self.move(global_pos)
        self.show()
        self.text_input.setFocus()

    # ── Posição ───────────────────────────────────────────────────────────────

    def _nudge(self, dx: float, dy: float) -> None:
        self._deslocamento[0] += dx
        self._deslocamento[1] += dy
        self._atualizar_deslocamento_lbl()
        self._avisar_posicao()

    def _avisar_posicao(self) -> None:
        """Pede a prévia na página — sem isso o usuário só descobre onde o texto foi parar
        depois de confirmar."""
        self.posicao_mudou.emit(self._spans, self._deslocamento[0], self._deslocamento[1])

    def _guardar_estado_inicial(self) -> None:
        self._inicial = {
            'bold': self.bold_btn.isChecked(),
            'italic': self.italic_btn.isChecked(),
            'size': float(self.size_spin.value()),
            'color': self._color,
            'family': self.font_combo.currentFont().family(),
        }

    def _mudou(self, campo, valor):
        """Devolve `valor` só se o usuário tiver mexido naquele controle; senão None.

        É o que permite alinhar vários trechos de formatações diferentes sem uniformizar:
        o que não foi tocado não vai no override, e cada trecho mantém o que já tinha."""
        return valor if self._inicial.get(campo) != valor else None

    def _escolher_alinhamento(self, chave) -> None:
        """Botões de alinhamento funcionam como rádio: só um fica marcado."""
        self._alinhamento = chave
        for c, botao in self.alinhamento_btns.items():
            botao.setChecked(c == chave)

    def _reset_posicao(self) -> None:
        self._deslocamento = [0.0, 0.0]
        self._atualizar_deslocamento_lbl()
        self._avisar_posicao()

    def _atualizar_deslocamento_lbl(self) -> None:
        dx, dy = self._deslocamento
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            self.deslocamento_lbl.setText('na posição original')
        else:
            self.deslocamento_lbl.setText(f'deslocado {dx:+.0f}, {dy:+.0f} pt')

    def _pick_color(self) -> None:
        r, g, b = (int(c * 255) for c in self._color)
        chosen = QColorDialog.getColor(QColor(r, g, b), self)
        if chosen.isValid():
            self._color = (chosen.redF(), chosen.greenF(), chosen.blueF())

    def _confirm(self) -> None:
        override = FormatOverride(
            bold=self._mudou('bold', self.bold_btn.isChecked()),
            italic=self._mudou('italic', self.italic_btn.isChecked()),
            size=self._mudou('size', float(self.size_spin.value())),
            color=self._mudou('color', self._color),
            # Só manda família quando o usuário trocou de fonte de propósito. O nome
            # que o PDF traz costuma vir com prefixo de subset ("ABCDEF+TimesNewRoman"),
            # que o QFontComboBox resolve para uma família genérica — mandá-lo sempre
            # impediria o motor de reencontrar e reutilizar a fonte embutida original.
            family=self._mudou('family', self.font_combo.currentFont().family()),
            alinhamento=self._alinhamento,
            entrelinha=self.entrelinha_combo.currentData(),
        )
        linhas = self.text_input.toPlainText().split('\n')
        if self._spans:
            # uma linha da caixa por trecho; o que sobrar vai junto com o último
            textos = linhas[:len(self._spans) - 1]
            textos.append('\n'.join(linhas[len(self._spans) - 1:]))
            # Trechos sem linha correspondente recebem '' (apagar). Ficar de fora da
            # lista seria pior: eles ja foram redigidos e sumiriam sem substituto.
            textos += [''] * (len(self._spans) - len(textos))
            self.confirmed.emit(self._spans, textos, override, tuple(self._deslocamento))
        else:
            self.confirmed.emit(None, ['\n'.join(linhas)], override, tuple(self._deslocamento))
        # Apaga o fantasma: sem isto ele fica desenhado por cima do texto que acabou de
        # ser movido, e parece que o trecho duplicou.
        self.posicao_mudou.emit([], 0.0, 0.0)
        self.hide()

    def _cancel(self) -> None:
        self.posicao_mudou.emit([], 0.0, 0.0)
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
