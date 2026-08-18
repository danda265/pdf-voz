from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import fitz

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


def test_fluxo_completo_editar_e_salvar_pela_interface(qtbot, sample_pdf, monkeypatch):
    """Percorre o caminho real: entra no modo edição, confirma uma edição e salva.

    Existe porque um NameError em _on_popup_confirmed passou por todos os testes de
    unidade e derrubava o app inteiro: no PyQt6 uma exceção não tratada dentro de um
    slot aborta o processo, levando junto as edições não salvas."""
    import gui as gui_mod
    from pdf_editor import FormatOverride, spans_for_page

    salvos = []
    monkeypatch.setattr(gui_mod.QMessageBox, 'information',
                        lambda *a, **k: salvos.append(a[-1]))
    monkeypatch.setattr(gui_mod.QMessageBox, 'critical',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(f'erro na UI: {a}')))
    monkeypatch.setattr(gui_mod.QMessageBox, 'question',
                        lambda *a, **k: gui_mod.QMessageBox.StandardButton.Discard)

    window = gui_mod.MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(sample_pdf)
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)
    assert window.edit_session is not None

    spans = spans_for_page(window.edit_session.doc[0])
    alvo = next(s for s in spans if s.text.strip() == 'Ola mundo')

    # passa pelo caminho real: abrir a caixa no trecho e então confirmar
    window._on_span_clicked(alvo)
    window._on_popup_confirmed([alvo], ['Texto trocado'], FormatOverride(), (0.0, 0.0))
    assert 'Texto trocado' in window.edit_session.doc[0].get_text()
    assert 'Edição aplicada' in window.status_label.text()

    # e salva
    window._save_edited_copy()
    assert salvos, 'não apareceu confirmação de salvamento'
    copia = sample_pdf.with_name(f'{sample_pdf.stem}_editado{sample_pdf.suffix}')
    assert copia.exists()
    assert 'Texto trocado' in fitz.open(str(copia))[0].get_text()

    window.edit_mode_button.setChecked(False)
    window.close()


def test_fluxo_de_varios_trechos_e_multilinha_pela_interface(qtbot, sample_pdf, monkeypatch):
    """Edição de vários trechos e texto com quebra — o caminho que introduziu o bug."""
    import gui as gui_mod
    from pdf_editor import FormatOverride, spans_for_page

    monkeypatch.setattr(gui_mod.QMessageBox, 'critical',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(f'erro na UI: {a}')))
    monkeypatch.setattr(gui_mod.QMessageBox, 'question',
                        lambda *a, **k: gui_mod.QMessageBox.StandardButton.Discard)
    window = gui_mod.MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(sample_pdf)
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)

    spans = spans_for_page(window.edit_session.doc[0])
    window._on_spans_selected(spans)
    window._on_popup_confirmed(spans, ['linha A\nlinha B'] + ['x'] * (len(spans) - 1),
                               FormatOverride(alinhamento='centro'), (0.0, 0.0))

    texto = window.edit_session.doc[0].get_text()
    assert 'linha A' in texto and 'linha B' in texto
    assert 'Edição aplicada' in window.status_label.text()
    window.edit_mode_button.setChecked(False)
    window.close()


def test_erro_inesperado_nao_derruba_o_app(qtbot, monkeypatch):
    """A rede de segurança tem de engolir a exceção e manter a janela viva — o PyQt6
    aborta o processo quando uma exceção escapa de um slot."""
    import sys as _sys
    import gui as gui_mod

    mostrados = []
    monkeypatch.setattr(gui_mod.QMessageBox, 'critical',
                        lambda *a, **k: mostrados.append(a[2] if len(a) > 2 else ''))
    hook_anterior = _sys.excepthook
    try:
        window = gui_mod.MainWindow()
        qtbot.addWidget(window)
        gui_mod._instalar_rede_de_seguranca(window)
        assert _sys.excepthook is not hook_anterior

        try:
            raise ValueError('falha simulada dentro de um slot')
        except ValueError:
            _sys.excepthook(*_sys.exc_info())   # não pode levantar nem matar o processo

        assert mostrados and 'falha simulada' in mostrados[0]
        assert 'continua aberto' in mostrados[0]
        window.close()
    finally:
        _sys.excepthook = hook_anterior


def _pdf_duas_paginas(tmp_path):
    caminho = tmp_path / 'duas.pdf'
    d = fitz.open()
    a = d.new_page(width=595, height=842)
    a.insert_text((72, 100), 'PAGINA UM ALVO', fontsize=12, fontname='helv')
    b = d.new_page(width=595, height=842)
    b.insert_text((72, 100), 'PAGINA DOIS INTACTA', fontsize=12, fontname='helv')
    d.save(str(caminho)); d.close()
    return caminho


def test_edicao_vai_para_a_pagina_do_trecho_mesmo_apos_rolar(qtbot, tmp_path, monkeypatch):
    """O documento rola contínuo, então não existe "página atual" para errar: cada trecho
    carrega a própria página. Antes, rolar até outra página fazia a edição cair nela,
    apagando conteúdo alheio."""
    import gui as gui_mod
    from pdf_editor import FormatOverride, spans_for_page

    monkeypatch.setattr(gui_mod.QMessageBox, 'critical',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(f'erro: {a}')))
    monkeypatch.setattr(gui_mod.QMessageBox, 'question',
                        lambda *a, **k: gui_mod.QMessageBox.StandardButton.Discard)

    window = gui_mod.MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(_pdf_duas_paginas(tmp_path))
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)

    alvo = next(s for s in spans_for_page(window.edit_session.doc[0]) if 'UM ALVO' in s.text)
    assert alvo.pagina == 0
    window._on_span_clicked(alvo)
    pagina_dois_antes = window.edit_session.doc[1].get_text()

    window._go_edit_page(1)   # rola até a página 2 com a caixa aberta
    window._on_popup_confirmed([alvo], ['TROCADO'], FormatOverride(), (0.0, 0.0))

    assert window.edit_session.doc[1].get_text() == pagina_dois_antes, 'mexeu na página errada'
    assert 'TROCADO' in window.edit_session.doc[0].get_text(), 'não editou a página do trecho'
    window.edit_mode_button.setChecked(False)
    window.close()


def test_selecao_que_mistura_paginas_e_recusada(qtbot, tmp_path, monkeypatch):
    import gui as gui_mod
    from pdf_editor import FormatOverride, spans_for_page

    erros = []
    monkeypatch.setattr(gui_mod.QMessageBox, 'critical', lambda *a, **k: erros.append(a))
    monkeypatch.setattr(gui_mod.QMessageBox, 'question',
                        lambda *a, **k: gui_mod.QMessageBox.StandardButton.Discard)

    window = gui_mod.MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(_pdf_duas_paginas(tmp_path))
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)

    de_p1 = spans_for_page(window.edit_session.doc[0])[0]
    de_p2 = spans_for_page(window.edit_session.doc[1])[0]
    antes = [window.edit_session.doc[i].get_text() for i in (0, 1)]

    window._on_popup_confirmed([de_p1, de_p2], ['A', 'B'], FormatOverride(), (0.0, 0.0))

    assert erros, 'aceitou uma seleção que mistura páginas'
    assert [window.edit_session.doc[i].get_text() for i in (0, 1)] == antes
    window.edit_mode_button.setChecked(False)
    window.close()


def test_apagar_linhas_da_selecao_nao_faz_texto_sumir(qtbot, tmp_path, monkeypatch):
    """Verificado em uso: selecionar 3 trechos e deixar 1 linha apagava os três da página
    e escrevia só a linha digitada — os trechos sem par eram redigidos e esquecidos."""
    import gui as gui_mod

    monkeypatch.setattr(gui_mod.QMessageBox, 'critical',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError(f'erro: {a}')))
    monkeypatch.setattr(gui_mod.QMessageBox, 'question',
                        lambda *a, **k: gui_mod.QMessageBox.StandardButton.Discard)

    caminho = tmp_path / 'tres.pdf'
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    for y, t in ((100, 'ALFA'), (130, 'BETA'), (160, 'GAMA')):
        pg.insert_text((72, y), t, fontsize=12, fontname='helv')
    d.save(str(caminho)); d.close()

    window = gui_mod.MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(caminho)
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)

    from pdf_editor import spans_for_page
    sel = spans_for_page(window.edit_session.doc[0])
    assert len(sel) == 3
    window._on_spans_selected(sel)
    window.edit_popup.text_input.setPlainText('SO UMA LINHA')
    window.edit_popup._confirm()

    final = window.edit_session.doc[0].get_text()
    assert 'SO UMA LINHA' in final
    # os trechos sem linha correspondente viram remoção INTENCIONAL, nunca sumiço silencioso
    assert window.edit_popup._spans == sel
    window.edit_mode_button.setChecked(False)
    window.close()


def test_sair_com_edicoes_nao_salvas_pergunta_antes_de_descartar(qtbot, sample_pdf, monkeypatch):
    """Verificado em uso: sair do modo edição jogava fora tudo sem uma palavra."""
    import gui as gui_mod
    from pdf_editor import FormatOverride, spans_for_page

    perguntas = []

    def responder(*a, **k):
        perguntas.append(a)
        return gui_mod.QMessageBox.StandardButton.Cancel   # usuário desiste de sair

    monkeypatch.setattr(gui_mod.QMessageBox, 'question', responder)
    window = gui_mod.MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(sample_pdf)
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)

    alvo = spans_for_page(window.edit_session.doc[0])[0]
    window._on_span_clicked(alvo)
    window._on_popup_confirmed([alvo], ['EDITADO'], FormatOverride(), (0.0, 0.0))
    assert window._edicoes_pendentes is True

    window.edit_mode_button.setChecked(False)   # tenta sair

    assert perguntas, 'saiu sem perguntar'
    assert window.edit_session is not None, 'descartou mesmo com o usuário cancelando'
    assert 'EDITADO' in window.edit_session.doc[0].get_text()

    monkeypatch.setattr(gui_mod.QMessageBox, 'question',
                        lambda *a, **k: gui_mod.QMessageBox.StandardButton.Discard)
    window.edit_mode_button.setChecked(False)
    assert window.edit_session is None
    window.close()
