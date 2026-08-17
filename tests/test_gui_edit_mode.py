from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from gui import MainWindow


def test_edit_mode_renders_first_page(qtbot, sample_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(sample_pdf)
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)
    assert window.edit_session is not None
    assert window.stack.currentIndex() == 1
    assert len(window.edit_scroll.canvas.spans) > 0
    window.close()


def test_documento_do_argv_aceita_pdf_existente(sample_pdf):
    from gui import _documento_do_argv
    assert _documento_do_argv(['app.exe', str(sample_pdf)]) == str(sample_pdf.resolve())


def test_documento_do_argv_ignora_flags_e_arquivo_inexistente(tmp_path):
    from gui import _documento_do_argv
    assert _documento_do_argv(['app.exe']) is None
    assert _documento_do_argv(['app.exe', '--debug']) is None
    assert _documento_do_argv(['app.exe', str(tmp_path / 'nao_existe.pdf')]) is None


def test_documento_do_argv_ignora_extensao_nao_suportada(tmp_path):
    from gui import _documento_do_argv
    outro = tmp_path / 'planilha.xlsx'
    outro.write_bytes(b'x')
    assert _documento_do_argv(['app.exe', str(outro)]) is None


def test_app_abre_com_documento_passado_na_linha_de_comando(qtbot, sample_pdf, monkeypatch):
    """Duplo clique no Explorer entrega o caminho por argv — o app tem de carregar o arquivo."""
    import gui

    carregados = []
    monkeypatch.setattr(gui.MainWindow, '_load_file', lambda self, path: carregados.append(path))
    window = gui.MainWindow()
    qtbot.addWidget(window)
    documento = gui._documento_do_argv(['PDF VOZ.exe', str(sample_pdf)])
    if documento:
        window._load_file(documento)
    window.close()
    assert carregados == [str(sample_pdf.resolve())]
