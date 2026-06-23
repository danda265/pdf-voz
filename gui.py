from __future__ import annotations

import itertools
import sys
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDragEnterEvent, QDropEvent, QFont,
    QKeySequence, QPalette, QShortcut, QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QProgressBar, QSlider, QTextEdit, QVBoxLayout, QWidget,
)

from audio_player import AudioPlayer
from document_reader import DocumentReader
from tts_engine import DEFAULT_VOICE, TTSEngine
from utils import clean_text, sanitize_error_message

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


# ── Threads ───────────────────────────────────────────────────────────────────


class LoaderThread(QThread):
    loaded   = pyqtSignal(str, int, str)
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
            self.loaded.emit(result.text, result.total_pages, result.kind)
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
            chunks = self.engine.split(self.text)
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
        self.temp_dir     = Path(__file__).resolve().parent / 'temp'
        self.speech_thread: Optional[SpeechThread] = None
        self.loader_thread: Optional[LoaderThread] = None
        self.export_thread: Optional[ExportThread] = None
        self._last_dir = str(Path.home())

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
        layout.addWidget(self._build_editor(), 1)
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
        self.theme_button.clicked.connect(self._toggle_theme)

        hbox.addWidget(self.open_button)
        hbox.addWidget(self.close_button)
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
            'Versão 1.0</p>'
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

    def _document_loaded(self, text: str, total_pages: int, kind: str) -> None:
        self.current_text = clean_text(text)
        self.total_pages  = total_pages
        self.editor.setPlainText(self.current_text)
        self.page_label.setText(f'Página 1 de {max(total_pages, 1)}')
        self.progress_bar.setValue(0)
        fname = Path(self.current_file).name if self.current_file else ''
        self.status_label.setText(
            f'{kind} carregado: "{fname}"  •  {len(self.current_text):,} caracteres'
        )
        self._set_reading_buttons(True)

    def close_document(self) -> None:
        self.stop_reading()
        self.current_file = None
        self.current_text = ''
        self.total_pages  = 0
        self.editor.clear()
        self.progress_bar.setValue(0)
        self.page_label.setText('—')
        self.status_label.setText('Arquivo fechado.')
        self._set_reading_buttons(False)
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
        self.stop_reading()   # para sem travar (não bloqueia)
        self.speech_thread = SpeechThread(
            self.current_text, voice,
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
        doc    = self.editor.document()
        cursor = doc.find(chunk[:min(180, len(chunk))])
        if cursor.isNull():
            cursor = doc.find(chunk[:min(60, len(chunk))])
        if not cursor.isNull():
            start = cursor.selectionStart()
            cursor.setPosition(start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                min(len(chunk), 2600),
            )
            fmt = QTextCharFormat()
            fmt.setBackground(QColor('#78350F' if self._dark else '#FEF08A'))
            ex        = QTextEdit.ExtraSelection()
            ex.cursor = cursor
            ex.format = fmt
            self.editor.setExtraSelections([ex])
            # rola sem criar seleção visível
            nav = self.editor.textCursor()
            nav.setPosition(start)
            self.editor.setTextCursor(nav)
            self.editor.ensureCursorVisible()
        self.progress_bar.setValue(int((index - 1) / max(total, 1) * 100))

    def _update_page_progress(self, current: int, total: int) -> None:
        self.page_label.setText(f'Página {current} de {total}')
        self.progress_bar.setValue(int(current / max(total, 1) * 100))

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


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
