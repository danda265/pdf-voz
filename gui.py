from __future__ import annotations

import bisect
import itertools
import re
import sys
import threading
import traceback
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtCore import QPoint, Qt, QThread, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDragEnterEvent, QDropEvent, QFont,
    QKeySequence, QPalette, QShortcut, QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QProgressBar, QSlider, QSpinBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from audio_player import AudioPlayer
from document_reader import DocumentReader
from tts_engine import DEFAULT_VOICE, TTSEngine
from utils import clean_text, sanitize_error_message
from pdf_editor import (
    EditSession, FormatOverride, PDFEditError, TextSpan,
    insert_free_text, open_for_edit, replace_spans_text, save_copy, spans_for_page,
)
from pdf_editor_view import PageScrollArea, SpanEditPopup

APP_VERSION = '1.2.0'   # fonte única da versão — o instalador (.iss) deve usar o mesmo valor

_FONT_MIN, _FONT_MAX, _FONT_DEFAULT = 12, 28, 15

_VOICE_ITEMS = [
    ('Francisca — feminina',  'pt-BR-FranciscaNeural'),
    ('Antônio — masculino',   'pt-BR-AntonioNeural'),
    ('Brenda — feminina',     'pt-BR-BrendaNeural'),
    ('Donato — masculino',    'pt-BR-DonatoNeural'),
    ('Elza — feminina',       'pt-BR-ElzaNeural'),
]
_DEFAULT_VOICE_IDX = next(
    (i for i, (_, v) in enumerate(_VOICE_ITEMS) if v == DEFAULT_VOICE), 0
)
_ALLOWED_VOICE_IDS = {v for _, v in _VOICE_ITEMS}
_SUPPORTED_EXTS = {'.pdf', '.docx', '.doc'}

# Contador global de sessões — garante nomes únicos de arquivos temp por leitura
_session_counter = itertools.count(1)


def _shorten_first_chunk(chunks: list, limit: int = 700) -> list:
    """Divide só o primeiro bloco numa fronteira de sentença para o áudio começar rápido.
    O restante mantém o tamanho normal (não deixa a leitura picotada)."""
    if not chunks or len(chunks[0]) <= limit:
        return chunks
    first = chunks[0]
    matches = list(re.finditer(r'[.!?;:]\s', first[:limit + 1]))
    cut = matches[-1].end() if matches else limit
    head, tail = first[:cut].strip(), first[cut:].strip()
    if not head or not tail:
        return chunks
    return [head, tail] + list(chunks[1:])


# ── Threads ───────────────────────────────────────────────────────────────────


class LoaderThread(QThread):
    loaded   = pyqtSignal(str, int, str, list)
    progress = pyqtSignal(int, int)
    error    = pyqtSignal(str)

    def __init__(self, path: str, use_ocr: bool):
        super().__init__()
        self.path = path
        self.use_ocr = use_ocr

    def run(self) -> None:
        try:
            reader = DocumentReader(use_ocr=self.use_ocr)
            result = reader.read(self.path, lambda c, t: self.progress.emit(c, t))
            self.loaded.emit(result.text, result.total_pages, result.kind, result.pages)
        except Exception as exc:
            self.error.emit(sanitize_error_message(str(exc)))


class SpeechThread(QThread):
    chunk_started = pyqtSignal(str, int, int)
    progress      = pyqtSignal(int, int)
    status        = pyqtSignal(str)
    error         = pyqtSignal(str)

    def __init__(self, text: str, voice: str, rate: int, volume: int, temp_dir: Path):
        super().__init__()
        self.text   = text
        self.voice  = voice
        self.volume = volume
        self.engine = TTSEngine(temp_dir)
        self.player = AudioPlayer()
        self._stop_event = threading.Event()
        # rate com lock para atualização em tempo real pelo slider
        self._rate      = rate
        self._rate_lock = threading.Lock()
        # prefixo único por sessão → evita colisão de arquivos entre leituras
        self._prefix = f'leitura_s{next(_session_counter):06d}_b'

    # chamado pela thread principal quando o slider muda
    def set_rate(self, rate: int) -> None:
        with self._rate_lock:
            self._rate = rate

    def set_volume(self, volume: int) -> None:
        self.volume = volume
        self.player.set_volume(volume)

    def _current_rate(self) -> int:
        with self._rate_lock:
            return self._rate

    def run(self) -> None:
        try:
            chunks = _shorten_first_chunk(self.engine.split(self.text))
            total  = len(chunks)
            if not total:
                self.status.emit('Nenhum texto para ler.')
                return
            self.player.set_volume(self.volume)
            for index, chunk in enumerate(chunks, start=1):
                if self._stop_event.is_set():
                    break
                self.status.emit(f'Sintetizando áudio {index}/{total}...')
                # lê a velocidade atual no momento da síntese (tempo real)
                rate = self._current_rate()
                audio_path = self.engine.synthesize_chunk(
                    chunk, index, self.voice, rate, self.volume,
                    prefix=self._prefix,
                )
                if self._stop_event.is_set():
                    break
                self.chunk_started.emit(chunk, index, total)
                self.status.emit(f'Reproduzindo bloco {index} de {total}...')
                self.player.play_file(audio_path, self._stop_event.is_set)
                self.progress.emit(index, total)
            self.status.emit(
                'Leitura interrompida.' if self._stop_event.is_set() else 'Leitura concluída.'
            )
        except Exception as exc:
            self.error.emit(sanitize_error_message(str(exc)))
        finally:
            self.player.stop()

    def pause_speech(self) -> None:
        self.player.pause()
        self.status.emit('Leitura pausada.')

    def resume_speech(self) -> None:
        self.player.resume()
        self.status.emit('Leitura retomada.')

    def stop_speech(self) -> None:
        self._stop_event.set()
        self.player.stop()


class ExportThread(QThread):
    status = pyqtSignal(str)
    done   = pyqtSignal(str)
    error  = pyqtSignal(str)

    def __init__(self, text: str, output_path: str, voice: str, rate: int, volume: int,
                 temp_dir: Path):
        super().__init__()
        self.text        = text
        self.output_path = output_path
        self.voice       = voice
        self.rate        = rate
        self.volume      = volume
        self.engine      = TTSEngine(temp_dir)

    def run(self) -> None:
        try:
            self.status.emit('Exportando narração MP3...')
            chunks = self.engine.split(self.text)
            self.engine.export_mp3(chunks, self.output_path, self.voice, self.rate, self.volume)
            self.done.emit(self.output_path)
        except Exception as exc:
            self.error.emit(sanitize_error_message(str(exc)))


# ── Main Window ───────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PDF VOZ — Leitor de Documentos')
        self.setMinimumSize(900, 640)
        self.resize(1200, 800)
        self.setAcceptDrops(True)

        self._dark = _system_is_dark()
        self._font_size = _FONT_DEFAULT
        self.current_file: Optional[str] = None
        self.current_text = ''
        self.total_pages  = 0
        self.pages: list[str] = []          # texto por página (PDF) para leitura a partir de N
        self._can_pick_page = False         # seletor de página inicial disponível?
        self._hl_pos = 0                    # posição do editor de onde buscar o próximo realce
        self._page_starts: list[int] = []   # posição no editor onde cada página começa (índice 0 = pág. 1)
        self.temp_dir     = Path(__file__).resolve().parent / 'temp'
        self.speech_thread: Optional[SpeechThread] = None
        self.loader_thread: Optional[LoaderThread] = None
        self.export_thread: Optional[ExportThread] = None
        self._last_dir = str(Path.home())
        self.edit_session: Optional[EditSession] = None
        self.edit_page_index = 0
        self._pending_new_point: Tuple[float, float] = (0.0, 0.0)

        self._build_ui()
        self._apply_theme()
        self.theme_button.setText('☀️' if self._dark else '🌙')
        self._setup_shortcuts()
        self._set_reading_buttons(False)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName('Root')
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_editor())     # indice 0: leitura
        self.stack.addWidget(self._build_edit_view())   # indice 1: edicao
        layout.addWidget(self.stack, 1)
        layout.addWidget(self._build_footer())
        self.setCentralWidget(root)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName('Header')
        header.setFixedHeight(66)
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(20, 0, 20, 0)
        hbox.setSpacing(10)

        title_col = QWidget()
        tcol = QVBoxLayout(title_col)
        tcol.setContentsMargins(0, 0, 0, 0)
        tcol.setSpacing(1)
        title = QLabel('PDF VOZ')
        title.setObjectName('AppTitle')
        sub = QLabel('PDF · Word · Voz Neural Brasileira')
        sub.setObjectName('AppSub')
        tcol.addWidget(title)
        tcol.addWidget(sub)
        hbox.addWidget(title_col)
        hbox.addStretch(1)

        self.open_button   = QPushButton('Abrir  PDF / Word')
        self.close_button  = QPushButton('Fechar arquivo')
        self.export_button = QPushButton('Exportar MP3')
        for btn in (self.open_button, self.close_button, self.export_button):
            btn.setObjectName('HeaderBtn')
            btn.setFixedHeight(36)
        self.theme_button = QPushButton('🌙')
        self.theme_button.setObjectName('ThemeBtn')
        self.theme_button.setToolTip('Alternar tema claro / escuro')
        self.theme_button.setFixedSize(40, 36)

        self.open_button.clicked.connect(self.open_document)
        self.close_button.clicked.connect(self.close_document)
        self.export_button.clicked.connect(self.export_mp3)
        self.about_button = QPushButton('ℹ')
        self.about_button.setObjectName('ThemeBtn')
        self.about_button.setToolTip('Sobre o PDF VOZ')
        self.about_button.setFixedSize(40, 36)
        self.about_button.clicked.connect(self._show_about)
        self.edit_mode_button = QPushButton('Editar PDF')
        self.edit_mode_button.setObjectName('HeaderBtn')
        self.edit_mode_button.setCheckable(True)
        self.edit_mode_button.setEnabled(False)
        self.edit_mode_button.setFixedHeight(36)
        self.edit_mode_button.toggled.connect(self._on_edit_mode_toggled)
        self.theme_button.clicked.connect(self._toggle_theme)

        hbox.addWidget(self.open_button)
        hbox.addWidget(self.close_button)
        hbox.addWidget(self.edit_mode_button)
        hbox.addWidget(self._vline())
        hbox.addWidget(self.export_button)
        hbox.addWidget(self._vline())
        hbox.addWidget(self.about_button)
        hbox.addWidget(self.theme_button)
        return header

    def _build_editor(self) -> QTextEdit:
        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setAcceptDrops(False)
        self.editor.setPlaceholderText(
            'Abra um arquivo PDF ou Word para começar.\n\n'
            'Você também pode arrastar e soltar o arquivo diretamente nesta janela.'
        )
        self._update_editor_font()
        # ao rolar, atualiza o rótulo com a página que está no topo do visor
        self.editor.verticalScrollBar().valueChanged.connect(self._on_editor_scrolled)
        return self.editor

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName('FooterPanel')
        vbox = QVBoxLayout(footer)
        vbox.setContentsMargins(20, 14, 20, 16)
        vbox.setSpacing(12)

        # ── Linha 1: Configurações ─────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(14)

        voice_lbl = QLabel('VOZ')
        voice_lbl.setObjectName('SectionLabel')
        self.voice_combo = QComboBox()
        for display, _ in _VOICE_ITEMS:
            self.voice_combo.addItem(display)
        self.voice_combo.setCurrentIndex(_DEFAULT_VOICE_IDX)

        speed_lbl = QLabel('VELOCIDADE')
        speed_lbl.setObjectName('SectionLabel')
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(-50, 50)
        self.speed_slider.setValue(0)
        self.speed_slider.setFixedWidth(110)
        self.speed_value_lbl = QLabel('+0%')
        self.speed_value_lbl.setObjectName('ValueLabel')
        self.speed_slider.valueChanged.connect(self._on_speed_changed)

        vol_lbl = QLabel('VOLUME')
        vol_lbl.setObjectName('SectionLabel')
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(110)
        self.volume_value_lbl = QLabel('100%')
        self.volume_value_lbl.setObjectName('ValueLabel')
        self.volume_slider.valueChanged.connect(self._on_volume_changed)

        font_lbl = QLabel('FONTE')
        font_lbl.setObjectName('SectionLabel')
        self.font_minus = QPushButton('A−')
        self.font_minus.setObjectName('FontBtn')
        self.font_minus.setFixedSize(36, 30)
        self.font_plus = QPushButton('A+')
        self.font_plus.setObjectName('FontBtn')
        self.font_plus.setFixedSize(36, 30)
        self.font_minus.clicked.connect(lambda: self._change_font(-1))
        self.font_plus.clicked.connect(lambda: self._change_font(+1))

        page_lbl = QLabel('INICIAR NA PÁGINA')
        page_lbl.setObjectName('SectionLabel')
        self.start_page_spin = QSpinBox()
        self.start_page_spin.setRange(1, 1)
        self.start_page_spin.setValue(1)
        self.start_page_spin.setFixedWidth(84)
        self.start_page_spin.setEnabled(False)
        self.start_page_spin.setToolTip('Página onde a leitura vai começar (1 = do início). Só para PDF.')

        self.ocr_checkbox = QCheckBox('OCR automático')
        self.ocr_checkbox.setChecked(True)

        row1.addWidget(voice_lbl)
        row1.addWidget(self.voice_combo)
        row1.addSpacing(6)
        row1.addWidget(speed_lbl)
        row1.addWidget(self.speed_slider)
        row1.addWidget(self.speed_value_lbl)
        row1.addSpacing(6)
        row1.addWidget(vol_lbl)
        row1.addWidget(self.volume_slider)
        row1.addWidget(self.volume_value_lbl)
        row1.addSpacing(6)
        row1.addWidget(font_lbl)
        row1.addWidget(self.font_minus)
        row1.addWidget(self.font_plus)
        row1.addSpacing(6)
        row1.addWidget(page_lbl)
        row1.addWidget(self.start_page_spin)
        row1.addStretch(1)
        row1.addWidget(self.ocr_checkbox)

        # ── Linha 2: Controles de reprodução ──────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self.read_button   = QPushButton('▶  Ler')
        self.read_button.setObjectName('BtnRead')
        self.read_button.setFixedHeight(40)
        self.pause_button  = QPushButton('⏸  Pausar')
        self.pause_button.setObjectName('BtnPause')
        self.pause_button.setFixedHeight(40)
        self.resume_button = QPushButton('▶  Continuar')
        self.resume_button.setObjectName('BtnResume')
        self.resume_button.setFixedHeight(40)
        self.stop_button   = QPushButton('⏹  Parar')
        self.stop_button.setObjectName('BtnStop')
        self.stop_button.setFixedHeight(40)

        self.read_button.clicked.connect(self.start_reading)
        self.pause_button.clicked.connect(self.pause_reading)
        self.resume_button.clicked.connect(self.resume_reading)
        self.stop_button.clicked.connect(self.stop_reading)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)

        self.page_label = QLabel('—')
        self.page_label.setObjectName('PageLabel')
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.page_label.setMinimumWidth(120)

        row2.addWidget(self.read_button)
        row2.addWidget(self.pause_button)
        row2.addWidget(self.resume_button)
        row2.addWidget(self.stop_button)
        row2.addSpacing(16)
        row2.addWidget(self.progress_bar, 1)
        row2.addSpacing(16)
        row2.addWidget(self.page_label)

        # ── Linha 3: Status ───────────────────────────────────
        self.status_label = QLabel('Pronto. Abra um arquivo PDF ou Word para começar.')
        self.status_label.setObjectName('StatusLabel')

        vbox.addLayout(row1)
        vbox.addLayout(row2)
        vbox.addWidget(self.status_label)
        return footer

    def _build_edit_view(self) -> QWidget:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName('EditToolbar')
        hbox = QHBoxLayout(toolbar)
        self.edit_prev_button = QPushButton('◀')
        self.edit_prev_button.clicked.connect(lambda: self._go_edit_page(-1))
        self.edit_page_label = QLabel('—')
        self.edit_next_button = QPushButton('▶')
        self.edit_next_button.clicked.connect(lambda: self._go_edit_page(1))
        self.add_text_button = QPushButton('Adicionar texto')
        self.add_text_button.setCheckable(True)
        self.add_text_button.toggled.connect(self._toggle_add_mode)
        self.edit_undo_button = QPushButton('Desfazer')
        self.edit_undo_button.clicked.connect(self._edit_undo)
        self.edit_save_button = QPushButton('Salvar cópia')
        self.edit_save_button.clicked.connect(self._save_edited_copy)
        hbox.addWidget(self.edit_prev_button)
        hbox.addWidget(self.edit_page_label)
        hbox.addWidget(self.edit_next_button)
        hbox.addSpacing(12)
        hbox.addWidget(self.add_text_button)
        hbox.addWidget(self.edit_undo_button)
        hbox.addStretch(1)
        hbox.addWidget(self.edit_save_button)
        vbox.addWidget(toolbar)

        self.edit_scroll = PageScrollArea()
        self.edit_scroll.canvas.span_clicked.connect(self._on_span_clicked)
        self.edit_scroll.canvas.free_area_clicked.connect(self._on_free_area_clicked)
        self.edit_scroll.canvas.span_moved.connect(self._on_span_moved)
        self.edit_scroll.canvas.spans_selected.connect(self._on_spans_selected)
        vbox.addWidget(self.edit_scroll, 1)

        self.edit_popup = SpanEditPopup(self)
        self.edit_popup.confirmed.connect(self._on_popup_confirmed)
        self.edit_popup.posicao_mudou.connect(self.edit_scroll.canvas.previsualizar)

        return container

    def _on_edit_mode_toggled(self, checked: bool) -> None:
        if checked:
            self._enter_edit_mode()
        else:
            self._exit_edit_mode()

    def _enter_edit_mode(self) -> None:
        if not self.current_file:
            return
        try:
            doc = open_for_edit(self.current_file)
        except PDFEditError as exc:
            QMessageBox.warning(self, 'Não é possível editar', str(exc))
            self.edit_mode_button.setChecked(False)
            return
        self.edit_session = EditSession(doc)
        self.edit_page_index = 0
        self.stack.setCurrentIndex(1)
        self._render_edit_page()

    def _exit_edit_mode(self) -> None:
        self.stack.setCurrentIndex(0)
        # A caixa agora é janela flutuante: não some sozinha ao sair do modo edição.
        self.edit_popup.hide()
        self.add_text_button.setChecked(False)   # não deixa o modo "Adicionar texto" preso
        self.edit_page_index = 0
        if self.edit_session:
            self.edit_session.doc.close()
            self.edit_session = None

    def _render_edit_page(self) -> None:
        if not self.edit_session:
            return
        page = self.edit_session.doc[self.edit_page_index]
        spans = spans_for_page(page)
        self.edit_scroll.canvas.show_page(page, spans)
        self.edit_page_label.setText(
            f'Página {self.edit_page_index + 1} de {self.edit_session.doc.page_count}'
        )

    def _go_edit_page(self, delta: int) -> None:
        if not self.edit_session:
            return
        new_index = self.edit_page_index + delta
        if 0 <= new_index < self.edit_session.doc.page_count:
            self.edit_page_index = new_index
            self._render_edit_page()

    def _toggle_add_mode(self, checked: bool) -> None:
        self.edit_scroll.canvas.set_add_mode(checked)

    def _on_spans_selected(self, spans: list) -> None:
        """Seleção por retângulo: abre a caixa com todos os trechos de uma vez."""
        primeiro = spans[0]
        local = QPoint(int(primeiro.origin[0] * self.edit_scroll.canvas.zoom),
                       int(primeiro.origin[1] * self.edit_scroll.canvas.zoom))
        self.edit_popup.open_for_spans(spans, self.edit_scroll.canvas.mapToGlobal(local))
        self.status_label.setText(
            f'{len(spans)} trecho(s) selecionado(s) — edite, alinhe ou mova tudo de uma vez.'
        )

    def _on_span_clicked(self, span: TextSpan) -> None:
        self.edit_scroll.canvas.destacar([span])
        x, y = span.origin
        local = QPoint(int(x * self.edit_scroll.canvas.zoom), int(y * self.edit_scroll.canvas.zoom))
        self.edit_popup.open_for_span(span, self.edit_scroll.canvas.mapToGlobal(local))

    def _on_free_area_clicked(self, x: float, y: float) -> None:
        self._pending_new_point = (x, y)
        local = QPoint(int(x * self.edit_scroll.canvas.zoom), int(y * self.edit_scroll.canvas.zoom))
        self.edit_popup.open_for_new_text(self.edit_scroll.canvas.mapToGlobal(local))

    def _on_span_moved(self, span: TextSpan, dx: float, dy: float) -> None:
        """Arrastou o trecho: abre a caixa já com o deslocamento, para o usuário conferir
        e ajustar nas setas antes de aplicar. Aplicar direto no soltar tornaria fácil mover
        sem querer, e o texto já teria sido reescrito."""
        self.edit_scroll.canvas.destacar([span])
        x, y = span.origin
        local = QPoint(int((x + dx) * self.edit_scroll.canvas.zoom),
                       int((y + dy) * self.edit_scroll.canvas.zoom))
        self.edit_popup.open_for_span(span, self.edit_scroll.canvas.mapToGlobal(local), (dx, dy))
        self.status_label.setText(
            f'Trecho movido {dx:+.0f}, {dy:+.0f} pt — confirme em OK ou ajuste nas setas.'
        )

    def _on_popup_confirmed(self, spans, textos: list, override: FormatOverride,
                            deslocamento=(0.0, 0.0)) -> None:
        if not self.edit_session:
            return
        page = self.edit_session.doc[self.edit_page_index]
        self.edit_session.snapshot()
        try:
            if spans:
                escolhas = replace_spans_text(self.edit_session.doc, page, spans, textos,
                                              override, deslocamento)
                choice = escolhas[0]
            else:
                choice = insert_free_text(self.edit_session.doc, page, self._pending_new_point,
                                          textos[0], override)
                escolhas = [choice]
        except Exception as exc:
            # Restaura o snapshot em vez de descartá-lo: a falha pode ter acontecido
            # com o documento já parcialmente alterado, e descartar deixaria o dano
            # sem nenhuma forma de desfazer.
            self.edit_session.undo()
            self._render_edit_page()
            self._show_error(sanitize_error_message(str(exc)))
            return
        self._render_edit_page()
        avisos = []
        if any(c.used_fallback for c in escolhas):
            avisos.append('fonte aproximada (a original não pôde ser reutilizada)')
        if any(c.overflowed for c in escolhas):
            avisos.append('alguma linha passou da largura do trecho original e pode '
                          'estar por cima do que vem depois — encurte o texto, quebre '
                          'em outra linha ou diminua a fonte')
        if any('\n' in t for t in textos):
            avisos.append('as linhas extras descem sobre a área abaixo — confira se '
                          'não cobriram nada')
        if avisos:
            self.status_label.setText('Edição aplicada — ' + '; '.join(avisos) + '.')
        else:
            self.status_label.setText('Edição aplicada.')

    def _undo_shortcut(self) -> None:
        """Ctrl+Z só desfaz edição de PDF; no modo leitura o atalho não faz nada."""
        if self.stack.currentIndex() == 1:
            self._edit_undo()

    def _edit_undo(self) -> None:
        if self.edit_session and self.edit_session.undo():
            self._render_edit_page()
        else:
            self.status_label.setText('Nada para desfazer.')

    def _save_edited_copy(self) -> None:
        if not self.edit_session or not self.current_file:
            return
        try:
            target = save_copy(self.edit_session.doc, self.current_file)
        except Exception as exc:
            # O fitz levanta erros próprios (FzErrorSystem etc.) que não herdam de
            # OSError — capturar só OSError deixaria a falha ao salvar sem aviso.
            self._show_error(sanitize_error_message(str(exc)))
            return
        QMessageBox.information(self, 'Salvo', f'Cópia editada salva em:\n{target}')

    # ── Sliders em tempo real ─────────────────────────────────────────────────

    def _on_speed_changed(self, value: int) -> None:
        self.speed_value_lbl.setText(f'{value:+d}%')
        if self.speech_thread:
            self.speech_thread.set_rate(value)

    def _on_volume_changed(self, value: int) -> None:
        self.volume_value_lbl.setText(f'{value}%')
        if self.speech_thread:
            self.speech_thread.set_volume(value)

    # ── Tema ──────────────────────────────────────────────────────────────────

    def _show_about(self) -> None:
        QMessageBox.about(
            self, 'Sobre o PDF VOZ',
            '<h2>PDF VOZ</h2>'
            '<p>Leitor de documentos com voz neural brasileira.</p>'
            '<p><b>Desenvolvido por:</b><br>Anderson Rodrigo Costa</p>'
            '<p style="color:#64748B;font-size:11px;">'
            'PDF · Word · OCR · Voz Microsoft Neural<br>'
            f'Versão {APP_VERSION}</p>'
        )

    def _toggle_theme(self) -> None:
        self._dark = not self._dark
        self.theme_button.setText('☀️' if self._dark else '🌙')
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.setStyleSheet(_build_stylesheet(self._dark))
        app = QApplication.instance()
        pal = app.palette()
        if self._dark:
            pal.setColor(QPalette.ColorRole.Base,       QColor('#1E293B'))
            pal.setColor(QPalette.ColorRole.Window,     QColor('#0F172A'))
            pal.setColor(QPalette.ColorRole.WindowText, QColor('#F1F5F9'))
            pal.setColor(QPalette.ColorRole.Text,       QColor('#F1F5F9'))
            pal.setColor(QPalette.ColorRole.Button,     QColor('#1E293B'))
            pal.setColor(QPalette.ColorRole.ButtonText, QColor('#F1F5F9'))
        else:
            pal.setColor(QPalette.ColorRole.Base,       QColor('#FFFFFF'))
            pal.setColor(QPalette.ColorRole.Window,     QColor('#EFF3F9'))
            pal.setColor(QPalette.ColorRole.WindowText, QColor('#0F172A'))
            pal.setColor(QPalette.ColorRole.Text,       QColor('#0F172A'))
            pal.setColor(QPalette.ColorRole.Button,     QColor('#FFFFFF'))
            pal.setColor(QPalette.ColorRole.ButtonText, QColor('#0F172A'))
        app.setPalette(pal)

    # ── Fonte ─────────────────────────────────────────────────────────────────

    def _change_font(self, delta: int) -> None:
        self._font_size = max(_FONT_MIN, min(_FONT_MAX, self._font_size + delta))
        self._update_editor_font()

    def _update_editor_font(self) -> None:
        self.editor.setFont(QFont('Segoe UI', self._font_size))

    # ── Arquivo ───────────────────────────────────────────────────────────────

    def open_document(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, 'Abrir arquivo', self._last_dir,
            'Documentos (*.pdf *.docx *.doc);;PDF (*.pdf);;Word (*.docx *.doc)',
        )
        if not path:
            return
        self._last_dir = str(Path(path).parent)
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        self.stop_reading()
        # Sai do modo edição antes de trocar de arquivo: manter a sessão antiga aberta
        # apontaria o "Salvar cópia" para o documento anterior gravado com o nome do novo.
        self.edit_mode_button.setChecked(False)
        self.current_file = path
        fname = Path(path).name
        self.editor.setPlainText(f'Carregando "{fname}"...')
        self.status_label.setText(f'Extraindo texto de "{fname}"...')
        self.progress_bar.setValue(0)

        self.loader_thread = LoaderThread(path, self.ocr_checkbox.isChecked())
        self.loader_thread.progress.connect(self._update_page_progress)
        self.loader_thread.loaded.connect(self._document_loaded)
        self.loader_thread.error.connect(self._show_error)
        self.loader_thread.finished.connect(self.loader_thread.deleteLater)
        self.loader_thread.start()

    def _document_loaded(self, text: str, total_pages: int, kind: str, pages: list) -> None:
        self.current_text = clean_text(text)
        self.total_pages  = total_pages
        self.pages        = list(pages) if pages else []
        self._page_starts = []   # limpa antes de preencher (evita mapear com dados do doc anterior)
        self.editor.setPlainText(self.current_text)
        self._page_starts = self._compute_page_starts(self.current_text)
        self.page_label.setText(f'Página 1 de {max(total_pages, 1)}')
        self.progress_bar.setValue(0)
        # seletor de página inicial: só para PDF com várias páginas e lista de páginas íntegra
        self._can_pick_page = (kind == 'PDF' and total_pages > 1 and len(self.pages) == total_pages)
        self.start_page_spin.setRange(1, total_pages if self._can_pick_page else 1)
        self.start_page_spin.setValue(1)
        self.start_page_spin.setSuffix(f' / {total_pages}' if self._can_pick_page else '')
        self.start_page_spin.setEnabled(self._can_pick_page)
        fname = Path(self.current_file).name if self.current_file else ''
        self.status_label.setText(
            f'{kind} carregado: "{fname}"  •  {len(self.current_text):,} caracteres'
        )
        self._set_reading_buttons(True)
        self.edit_mode_button.setEnabled(kind == 'PDF')

    def close_document(self) -> None:
        self.stop_reading()
        self.current_file = None
        self.current_text = ''
        self.total_pages  = 0
        self.pages        = []
        self._page_starts = []
        self._can_pick_page = False
        self.editor.clear()
        self.progress_bar.setValue(0)
        self.page_label.setText('—')
        self.status_label.setText('Arquivo fechado.')
        self.start_page_spin.setRange(1, 1)
        self.start_page_spin.setValue(1)
        self.start_page_spin.setSuffix('')
        self.start_page_spin.setEnabled(False)
        self._set_reading_buttons(False)
        self.edit_mode_button.setEnabled(False)
        self.edit_mode_button.setChecked(False)
        self._clear_temp_audio()

    # ── Leitura ───────────────────────────────────────────────────────────────

    def _selected_voice(self) -> str:
        idx = self.voice_combo.currentIndex()
        if 0 <= idx < len(_VOICE_ITEMS):
            return _VOICE_ITEMS[idx][1]
        return DEFAULT_VOICE

    def start_reading(self) -> None:
        if not self.current_text.strip():
            QMessageBox.information(self, 'Sem texto', 'Abra um arquivo com texto antes de iniciar.')
            return
        voice = self._selected_voice()
        if voice not in _ALLOWED_VOICE_IDS:
            QMessageBox.warning(self, 'Voz inválida', 'Selecione uma voz válida da lista.')
            return
        # texto a ler: da página escolhida em diante (1 = do início / documento inteiro)
        start_page = self.start_page_spin.value()
        if self._can_pick_page and self.pages and 1 < start_page <= len(self.pages):
            text_to_read = '\n\n'.join(self.pages[start_page - 1:]).strip()
            if not text_to_read:
                QMessageBox.information(
                    self, 'Sem texto',
                    f'A partir da página {start_page} não há texto para ler.'
                )
                return
            self.status_label.setText(
                f'Iniciando na página {start_page} de {self.total_pages}...'
            )
        else:
            start_page = 1
            text_to_read = self.current_text
        self.stop_reading()   # para sem travar (não bloqueia)
        self._scroll_to_page(start_page)   # já mostra na tela onde a leitura vai começar
        self.speech_thread = SpeechThread(
            text_to_read, voice,
            self.speed_slider.value(), self.volume_slider.value(),
            self.temp_dir,
        )
        self.speech_thread.chunk_started.connect(self._highlight_chunk)
        self.speech_thread.progress.connect(self._update_reading_progress)
        self.speech_thread.status.connect(self.status_label.setText)
        self.speech_thread.error.connect(self._show_error)
        self.speech_thread.finished.connect(self._reading_finished)
        self.speech_thread.finished.connect(self.speech_thread.deleteLater)
        self._set_controls_during_reading(True)
        self.speech_thread.start()

    def pause_reading(self) -> None:
        if self.speech_thread:
            self.speech_thread.pause_speech()

    def resume_reading(self) -> None:
        if self.speech_thread:
            self.speech_thread.resume_speech()

    def stop_reading(self) -> None:
        """Para a leitura sem bloquear a thread principal."""
        if self.speech_thread:
            # desconecta _reading_finished para a thread antiga não resetar UI
            # quando terminar depois que uma nova leitura já iniciou
            try:
                self.speech_thread.finished.disconnect(self._reading_finished)
            except TypeError:
                pass
            self.speech_thread.stop_speech()
            self.speech_thread = None
        self._set_controls_during_reading(False)

    def export_mp3(self) -> None:
        if not self.current_text.strip():
            QMessageBox.information(self, 'Sem texto', 'Abra um arquivo antes de exportar.')
            return
        voice = self._selected_voice()
        if voice not in _ALLOWED_VOICE_IDS:
            QMessageBox.warning(self, 'Voz inválida', 'Selecione uma voz válida da lista.')
            return
        output_path, _ = QFileDialog.getSaveFileName(
            self, 'Exportar MP3',
            str(Path.home() / 'narracao.mp3'),
            'MP3 (*.mp3)',
        )
        if not output_path:
            return
        if not output_path.lower().endswith('.mp3'):
            output_path += '.mp3'
        self.export_thread = ExportThread(
            self.current_text, output_path, voice,
            self.speed_slider.value(), self.volume_slider.value(),
            self.temp_dir,
        )
        self.export_thread.status.connect(self.status_label.setText)
        self.export_thread.done.connect(
            lambda _: QMessageBox.information(self, 'Exportado', 'MP3 salvo com sucesso!')
        )
        self.export_thread.error.connect(self._show_error)
        self.export_thread.finished.connect(self.export_thread.deleteLater)
        self.export_thread.start()

    # ── Highlight ─────────────────────────────────────────────────────────────

    def _highlight_chunk(self, chunk: str, index: int, total: int) -> None:
        doc = self.editor.document()
        # QTextDocument.find NÃO casa strings com '\n' — busca pela 1ª linha não-vazia do trecho
        key = ''
        for line in chunk.split('\n'):
            line = line.strip()
            if line:
                key = line[:120]
                break
        cursor = self._find_forward(doc, key) if key else QTextCursor(doc)
        if key and not cursor.isNull():
            start = cursor.selectionStart()
            hl = QTextCursor(doc)
            hl.setPosition(start)
            hl.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                min(len(chunk), 2600),
            )
            fmt = QTextCharFormat()
            fmt.setBackground(QColor('#78350F' if self._dark else '#FEF08A'))
            ex        = QTextEdit.ExtraSelection()
            ex.cursor = hl
            ex.format = fmt
            self.editor.setExtraSelections([ex])
            # rola sem criar seleção visível
            nav = self.editor.textCursor()
            nav.setPosition(start)
            self.editor.setTextCursor(nav)
            self.editor.ensureCursorVisible()
            self._hl_pos = start + len(key)   # próxima busca avança a partir daqui
        self.progress_bar.setValue(int((index - 1) / max(total, 1) * 100))

    def _find_forward(self, doc, key: str) -> 'QTextCursor':
        """Procura key a partir de self._hl_pos; se não achar adiante, tenta do início."""
        pos = min(max(self._hl_pos, 0), max(0, doc.characterCount() - 1))
        origin = QTextCursor(doc)
        origin.setPosition(pos)
        cursor = doc.find(key, origin)
        if cursor.isNull():
            cursor = doc.find(key)
        return cursor

    def _scroll_to_page(self, page: int) -> None:
        """Rola o editor para o início da página indicada (1 = topo do documento)."""
        doc = self.editor.document()
        if page <= 1:
            self._hl_pos = 0
            nav = self.editor.textCursor()
            nav.setPosition(0)
            self.editor.setTextCursor(nav)
            self.editor.ensureCursorVisible()
            return
        cursor = doc.find(f'--- Pagina {page} de')
        if cursor.isNull():
            self._hl_pos = 0
            return
        start = cursor.selectionStart()
        self._hl_pos = start
        # deixa a página perto do topo do visor: vai ao fim e volta ao alvo
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        nav = self.editor.textCursor()
        nav.setPosition(start)
        self.editor.setTextCursor(nav)
        self.editor.ensureCursorVisible()

    def _update_page_progress(self, current: int, total: int) -> None:
        self.page_label.setText(f'Página {current} de {total}')
        self.progress_bar.setValue(int(current / max(total, 1) * 100))

    def _compute_page_starts(self, text: str) -> list[int]:
        """Posição inicial de cada marcador '--- Pagina N de ... ---' no texto do editor.
        Índice 0 = página 1. Fica vazio para Word (que não tem marcadores de página)."""
        return [m.start() for m in re.finditer(r'---\s*Pagina\s+\d+\s+de\s+\d+\s*---', text)]

    def _page_at_position(self, pos: int) -> int:
        """Página cujo marcador é o último a começar em ou antes de `pos`."""
        idx = bisect.bisect_right(self._page_starts, pos)
        return max(1, min(idx, self.total_pages))

    def _on_editor_scrolled(self, _value: int = 0) -> None:
        """Ao rolar o editor, atualiza o rótulo com a página visível no topo do visor."""
        if not self._page_starts or self.total_pages <= 0:
            return
        cursor = self.editor.cursorForPosition(QPoint(4, 4))
        self.page_label.setText(
            f'Página {self._page_at_position(cursor.position())} de {self.total_pages}'
        )

    def _update_reading_progress(self, current: int, total: int) -> None:
        self.progress_bar.setValue(int(current / max(total, 1) * 100))

    # ── Estado ────────────────────────────────────────────────────────────────

    def _reading_finished(self) -> None:
        self._set_controls_during_reading(False)
        self.speech_thread = None
        self.editor.setExtraSelections([])

    def _set_reading_buttons(self, enabled: bool) -> None:
        self.read_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.close_button.setEnabled(enabled)
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    def _set_controls_during_reading(self, reading: bool) -> None:
        has_text = bool(self.current_text.strip())
        self.read_button.setEnabled(has_text and not reading)
        self.pause_button.setEnabled(reading)
        self.resume_button.setEnabled(reading)
        self.stop_button.setEnabled(reading)
        self.open_button.setEnabled(not reading)
        self.export_button.setEnabled(has_text and not reading)
        self.start_page_spin.setEnabled(self._can_pick_page and not reading)

    def _show_error(self, message: str) -> None:
        self.status_label.setText('Ocorreu um erro.')
        QMessageBox.critical(self, 'Erro', message)

    # ── Drag & Drop ───────────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                if Path(urls[0].toLocalFile()).suffix.lower() in _SUPPORTED_EXTS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            path = urls[0].toLocalFile()
            if Path(path).suffix.lower() in _SUPPORTED_EXTS:
                event.acceptProposedAction()
                self._load_file(path)
                return
        event.ignore()

    # ── Atalhos ───────────────────────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence('Ctrl+O'), self).activated.connect(self.open_document)
        QShortcut(QKeySequence('Ctrl+W'), self).activated.connect(self.close_document)
        QShortcut(QKeySequence('Ctrl+E'), self).activated.connect(self.export_mp3)
        QShortcut(QKeySequence('Ctrl+Z'), self).activated.connect(self._undo_shortcut)
        QShortcut(QKeySequence('Space'),  self).activated.connect(self._space_toggle)
        QShortcut(QKeySequence('Escape'), self).activated.connect(self.stop_reading)

    def _space_toggle(self) -> None:
        if not self.speech_thread:
            return
        if self.pause_button.isEnabled():
            self.pause_reading()
        elif self.resume_button.isEnabled():
            self.resume_reading()

    # ── Limpeza ───────────────────────────────────────────────────────────────

    def _clear_temp_audio(self) -> None:
        if self.temp_dir.exists():
            for f in self.temp_dir.glob('leitura_*.mp3'):
                try:
                    f.unlink()
                except OSError:
                    pass

    def closeEvent(self, event) -> None:
        if self.speech_thread:
            self.speech_thread.stop_speech()
            self.speech_thread.wait(3000)
        if self.edit_session:
            # fecha o documento de edição aberto mesmo se o usuário nunca saiu do modo Editar PDF
            self.edit_session.doc.close()
            self.edit_session = None
        self._clear_temp_audio()
        event.accept()

    @staticmethod
    def _vline() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedWidth(1)
        f.setFixedHeight(30)
        f.setStyleSheet('QFrame { background: rgba(255,255,255,0.25); }')
        return f


# ── Stylesheet ────────────────────────────────────────────────────────────────


def _build_stylesheet(dark: bool) -> str:
    if dark:
        bg, surface, text = '#0F172A', '#1E293B', '#F1F5F9'
        subtext, border, editor_bg = '#94A3B8', '#334155', '#1E293B'
        label, prog_bg = '#CBD5E1', '#334155'
        hdr_from, hdr_to = '#0F172A', '#1E3A8A'
        font_hover = '#1E293B'
        dis_bg, dis_fg = '#334155', '#64748B'
    else:
        bg, surface, text = '#EFF3F9', '#FFFFFF', '#0F172A'
        subtext, border, editor_bg = '#64748B', '#E2E8F0', '#FFFFFF'
        label, prog_bg = '#374151', '#E2E8F0'
        hdr_from, hdr_to = '#1E3A8A', '#2563EB'
        font_hover = '#EFF6FF'
        dis_bg, dis_fg = '#D1D5DB', '#9CA3AF'

    return f"""
    QMainWindow, QWidget#Root {{ background: {bg}; }}
    #Header {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {hdr_from}, stop:1 {hdr_to});
    }}
    #AppTitle {{ color:#FFFFFF; font-size:18px; font-weight:700; }}
    #AppSub   {{ color:rgba(255,255,255,0.68); font-size:11px; }}
    #HeaderBtn {{
        background:rgba(255,255,255,0.14); color:#FFFFFF;
        border:1px solid rgba(255,255,255,0.30);
        border-radius:8px; padding:7px 16px; font-weight:600; font-size:13px;
    }}
    #HeaderBtn:hover {{ background:rgba(255,255,255,0.26); }}
    #HeaderBtn:disabled {{ color:rgba(255,255,255,0.35); border-color:rgba(255,255,255,0.12); }}
    #ThemeBtn {{
        background:rgba(255,255,255,0.12); color:#FFFFFF;
        border:1px solid rgba(255,255,255,0.25);
        border-radius:8px; font-size:16px;
    }}
    #ThemeBtn:hover {{ background:rgba(255,255,255,0.24); }}
    QTextEdit {{
        background:{editor_bg}; color:{text};
        border:none; padding:24px 28px;
        selection-background-color:#BFDBFE; selection-color:#1E3A8A;
    }}
    #FooterPanel {{ background:{surface}; border-top:2px solid {border}; }}
    QLabel {{ color:{label}; font-size:13px; }}
    #SectionLabel {{ color:{subtext}; font-size:10px; font-weight:700; letter-spacing:1.1px; }}
    #ValueLabel   {{ color:#3B82F6; font-weight:700; font-size:13px; min-width:42px; }}
    #PageLabel    {{ color:{text}; font-weight:600; font-size:13px; }}
    #StatusLabel  {{ color:{subtext}; font-size:12px; }}
    QComboBox {{
        background:{surface}; color:{text};
        border:1.5px solid {border}; border-radius:7px;
        padding:5px 10px; font-size:13px; min-height:32px; min-width:210px;
    }}
    QComboBox:hover {{ border-color:#93C5FD; }}
    QComboBox::drop-down {{ border:none; width:20px; }}
    QComboBox QAbstractItemView {{
        background:{surface}; color:{text}; border:1px solid {border};
        selection-background-color:#3B82F6; selection-color:white;
    }}
    QSpinBox {{
        background:{surface}; color:{text};
        border:1.5px solid {border}; border-radius:7px;
        padding:4px 6px; font-size:13px; min-height:32px;
    }}
    QSpinBox:hover {{ border-color:#93C5FD; }}
    QSpinBox:disabled {{ color:{dis_fg}; background:{dis_bg}; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width:16px; border:none; background:transparent; }}
    QSlider::groove:horizontal {{ background:{prog_bg}; height:5px; border-radius:3px; }}
    QSlider::handle:horizontal {{ background:#3B82F6; width:16px; height:16px; border-radius:8px; margin:-6px 0; }}
    QSlider::sub-page:horizontal {{ background:#3B82F6; border-radius:3px; }}
    QCheckBox {{ color:{label}; font-size:13px; spacing:7px; }}
    QCheckBox::indicator {{ width:16px; height:16px; border-radius:4px; border:2px solid {border}; background:{surface}; }}
    QCheckBox::indicator:checked {{ background:#3B82F6; border-color:#3B82F6; }}
    QProgressBar {{ background:{prog_bg}; border:none; border-radius:5px; height:10px; }}
    QProgressBar::chunk {{
        background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2563EB, stop:1 #7C3AED);
        border-radius:5px;
    }}
    #BtnRead   {{ background:#16A34A; color:white; border:none; border-radius:8px; padding:10px 22px; font-weight:700; font-size:14px; min-width:95px; }}
    #BtnRead:hover {{ background:#15803D; }}
    #BtnRead:disabled {{ background:{dis_bg}; color:{dis_fg}; }}
    #BtnPause  {{ background:#D97706; color:white; border:none; border-radius:8px; padding:10px 22px; font-weight:700; font-size:14px; min-width:95px; }}
    #BtnPause:hover {{ background:#B45309; }}
    #BtnPause:disabled {{ background:{dis_bg}; color:{dis_fg}; }}
    #BtnResume {{ background:#0891B2; color:white; border:none; border-radius:8px; padding:10px 22px; font-weight:700; font-size:14px; min-width:95px; }}
    #BtnResume:hover {{ background:#0E7490; }}
    #BtnResume:disabled {{ background:{dis_bg}; color:{dis_fg}; }}
    #BtnStop   {{ background:#DC2626; color:white; border:none; border-radius:8px; padding:10px 22px; font-weight:700; font-size:14px; min-width:95px; }}
    #BtnStop:hover {{ background:#B91C1C; }}
    #BtnStop:disabled {{ background:{dis_bg}; color:{dis_fg}; }}
    #FontBtn {{
        background:{surface}; color:{text}; border:1.5px solid {border};
        border-radius:6px; padding:4px 6px; font-weight:700; font-size:14px;
    }}
    #FontBtn:hover {{ border-color:#93C5FD; background:{font_hover}; }}
    QScrollBar:vertical {{ background:{surface}; width:8px; margin:0; border-radius:4px; }}
    QScrollBar::handle:vertical {{ background:{border}; border-radius:4px; min-height:20px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    """


# ── Helpers ───────────────────────────────────────────────────────────────────


def _system_is_dark() -> bool:
    try:
        bg = QApplication.instance().palette().color(QPalette.ColorRole.Window)
        return bg.lightness() < 128
    except Exception:
        return False


# ── Entry point ───────────────────────────────────────────────────────────────


def _documento_do_argv(argv: list[str]) -> Optional[str]:
    """Documento passado na linha de comando — é assim que o Windows entrega o arquivo
    quando o usuário dá duplo clique nele com o PDF VOZ associado."""
    for arg in argv[1:]:
        if arg.startswith('-'):
            continue
        caminho = Path(arg)
        if caminho.suffix.lower() in _SUPPORTED_EXTS and caminho.is_file():
            return str(caminho.resolve())
    return None


def _instalar_rede_de_seguranca(window: 'MainWindow') -> None:
    """Impede que um erro inesperado feche o app levando as edições junto.

    O PyQt6 aborta o processo quando uma exceção escapa de um slot — o app some da tela
    sem aviso. Num editor isso é perda de trabalho: melhor mostrar o erro e deixar o
    usuário salvar o que já fez."""
    def tratar(tipo, valor, tb) -> None:
        traceback.print_exception(tipo, valor, tb)
        try:
            QMessageBox.critical(
                window, 'Erro inesperado',
                sanitize_error_message(f'{tipo.__name__}: {valor}')
                + '\n\nO aplicativo continua aberto. Se havia edições, '
                  'use "Salvar cópia" antes de fechar.'
            )
        except Exception:
            pass   # nunca deixar o próprio tratador derrubar o app

    sys.excepthook = tratar


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    _instalar_rede_de_seguranca(window)
    window.show()
    documento = _documento_do_argv(sys.argv)
    if documento:
        window._load_file(documento)
    sys.exit(app.exec())
