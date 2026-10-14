from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import fitz
import pytest
from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtWidgets import QMessageBox

from gui import MainWindow
from pdf_merge_dialog import JuntarDialog, JuntarThread
from pdf_merge import EntradaJuntar


def _pdf(caminho, rotulo: str, paginas: int):
    doc = fitz.open()
    for n in range(1, paginas + 1):
        doc.new_page(width=595, height=842).insert_text((72, 100), f'{rotulo}-{n}', fontsize=14, fontname='helv')
    doc.save(str(caminho))
    doc.close()
    return caminho


def _rotulos(caminho) -> list:
    with fitz.open(str(caminho)) as doc:
        return [p.get_text().strip() for p in doc]


@pytest.fixture
def a(tmp_path):
    return _pdf(tmp_path / 'a.pdf', 'A', 3)


@pytest.fixture
def b(tmp_path):
    return _pdf(tmp_path / 'b.pdf', 'B', 4)


@pytest.fixture
def dialogo(qtbot, a, b):
    d = JuntarDialog(None, str(a.parent))
    qtbot.addWidget(d)
    d._adicionar_caminhos([str(a), str(b)])
    return d


def _nomes(d) -> list:
    return [d.tabela.item(i, 0).text() for i in range(d.tabela.rowCount())]


def test_lista_comeca_vazia_e_juntar_fica_desligado(qtbot):
    d = JuntarDialog()
    qtbot.addWidget(d)
    assert d.tabela.rowCount() == 0 and not d.botao_juntar.isEnabled()
    assert 'Nenhum arquivo' in d.resumo.text()


def test_adiciona_arquivos_e_resume(dialogo):
    assert _nomes(dialogo) == ['a.pdf', 'b.pdf']
    assert [dialogo.tabela.item(i, 1).text() for i in range(2)] == ['3', '4']
    assert dialogo.resumo.text() == '2 arquivos  •  7 páginas no resultado'
    assert dialogo.botao_juntar.isEnabled()


def test_subir_descer_e_remover(dialogo):
    dialogo.tabela.selectRow(1)
    dialogo._mover(-1)
    assert _nomes(dialogo) == ['b.pdf', 'a.pdf'] and dialogo.tabela.currentRow() == 0
    assert not dialogo.botao_subir.isEnabled() and dialogo.botao_descer.isEnabled()
    dialogo._mover(-1)                      # ja esta no topo: nada muda
    assert _nomes(dialogo) == ['b.pdf', 'a.pdf']
    dialogo._mover(+1)
    assert _nomes(dialogo) == ['a.pdf', 'b.pdf']
    dialogo.tabela.selectRow(0)
    dialogo._remover()
    assert _nomes(dialogo) == ['b.pdf'] and dialogo.resumo.text() == '1 arquivo  •  4 páginas no resultado'
    dialogo._remover()
    assert _nomes(dialogo) == [] and not dialogo.botao_juntar.isEnabled()


def test_paginas_invalidas_travam_o_botao_ate_corrigir(dialogo):
    dialogo.tabela.item(1, 2).setText('9')          # b.pdf so tem 4 paginas
    assert not dialogo.botao_juntar.isEnabled()
    assert 'b.pdf' in dialogo.resumo.text() and 'Corrija' in dialogo.resumo.text()
    assert 'não existe' in dialogo.tabela.item(1, 2).toolTip()
    dialogo.tabela.item(1, 2).setText('2-3')
    assert dialogo.botao_juntar.isEnabled()
    assert dialogo.resumo.text() == '2 arquivos  •  5 páginas no resultado'


def test_recusa_pdf_ruim_sem_mexer_na_lista(dialogo, tmp_path):
    ruim = tmp_path / 'ruim.pdf'
    ruim.write_bytes(b'nao e pdf')
    trancado = tmp_path / 'trancado.pdf'
    with fitz.open(str(tmp_path / 'a.pdf')) as doc:
        doc.save(str(trancado), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='x', owner_pw='y')
    problemas = dialogo._adicionar_caminhos([str(ruim), str(trancado)])
    assert len(problemas) == 2 and 'senha' in problemas[1]
    assert _nomes(dialogo) == ['a.pdf', 'b.pdf']


def test_junta_de_ponta_a_ponta_e_oferece_abrir(qtbot, dialogo, tmp_path, monkeypatch):
    dialogo.tabela.selectRow(1)
    dialogo._mover(-1)                                # b antes de a
    dialogo.tabela.item(1, 2).setText('1, 3')         # a.pdf: paginas 1 e 3
    perguntas = []
    monkeypatch.setattr(dialogo, '_perguntar_se_abre', lambda texto: perguntas.append(texto) or True)
    destino = tmp_path / 'saida.pdf'
    with qtbot.waitSignal(dialogo.abrir_resultado, timeout=10000) as sinal:
        dialogo._iniciar(str(destino))
    assert sinal.args == [str(destino)]
    assert _rotulos(destino) == ['B-1', 'B-2', 'B-3', 'B-4', 'A-1', 'A-3']
    assert '6 páginas' in perguntas[0] and dialogo.result() == dialogo.DialogCode.Accepted


def test_nao_abre_o_resultado_se_o_usuario_fechar(qtbot, dialogo, tmp_path, monkeypatch):
    monkeypatch.setattr(dialogo, '_perguntar_se_abre', lambda texto: False)
    abertos = []
    dialogo.abrir_resultado.connect(abertos.append)
    destino = tmp_path / 'saida.pdf'
    dialogo._iniciar(str(destino))
    qtbot.waitUntil(lambda: dialogo._thread is None, timeout=10000)
    assert destino.exists() and abertos == []


def test_erro_do_motor_aparece_e_libera_a_janela(qtbot, dialogo, a, monkeypatch):
    erros = []
    monkeypatch.setattr(QMessageBox, 'critical', staticmethod(lambda *args: erros.append(args[2])))
    dialogo._iniciar(str(a))            # saida = um dos arquivos de entrada: recusado
    qtbot.waitUntil(lambda: dialogo._thread is None, timeout=10000)
    assert len(erros) == 1 and 'saída' in erros[0]
    assert dialogo.botao_juntar.isEnabled() and not dialogo.progresso.isVisible()


def test_thread_cancelada_antes_de_comecar_nao_grava(qtbot, a, b, tmp_path):
    destino = tmp_path / 'saida.pdf'
    thread = JuntarThread([EntradaJuntar(str(a)), EntradaJuntar(str(b))], str(destino))
    concluidos, erros = [], []
    thread.done.connect(concluidos.append)
    thread.error.connect(erros.append)
    thread.cancelar()
    thread.start()
    assert thread.wait(10000)
    assert concluidos == [] and erros == [] and not destino.exists()
    assert list(tmp_path.glob('*.parcial')) == []


def test_fechar_a_janela_no_meio_nao_deixa_thread_rodando(qtbot, dialogo, tmp_path, monkeypatch):
    monkeypatch.setattr(dialogo, '_perguntar_se_abre', lambda texto: False)
    dialogo._iniciar(str(tmp_path / 'saida.pdf'))
    dialogo.reject()
    assert dialogo._thread is None or not dialogo._thread.isRunning()


def test_sugestao_de_saida_nao_sobrescreve(dialogo, tmp_path):
    assert dialogo._sugestao_de_saida() == str(tmp_path / 'juntado.pdf')
    (tmp_path / 'juntado.pdf').write_bytes(b'x')
    (tmp_path / 'juntado_2.pdf').write_bytes(b'x')
    assert dialogo._sugestao_de_saida() == str(tmp_path / 'juntado_3.pdf')


def test_arrastar_aceita_so_pdf(a, tmp_path):
    class Evento:
        def __init__(self, caminhos):
            self._mime = QMimeData()
            self._mime.setUrls([QUrl.fromLocalFile(str(c)) for c in caminhos])

        def mimeData(self):
            return self._mime

    texto = tmp_path / 'nota.txt'
    texto.write_text('x')
    assert [Path(p) for p in JuntarDialog._pdfs_do_arraste(Evento([a, texto]))] == [a]
    assert JuntarDialog._pdfs_do_arraste(Evento([texto])) == []


# ── ligacao com a janela principal ───────────────────────────────────────────

def test_botao_juntar_existe_sem_documento_aberto(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.merge_button.isEnabled()
    dialogo = window._criar_dialogo_juntar()
    qtbot.addWidget(dialogo)
    assert dialogo.tabela.rowCount() == 0
    window.close()


def test_pdf_aberto_ja_entra_na_lista_e_word_nao(qtbot, a):
    window = MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(a)
    window._document_loaded('texto', 3, 'PDF', ['x', 'y', 'z'])
    dialogo = window._criar_dialogo_juntar()
    qtbot.addWidget(dialogo)
    assert _nomes(dialogo) == ['a.pdf']
    window._document_loaded('texto', 1, 'Word', [])
    outro = window._criar_dialogo_juntar()
    qtbot.addWidget(outro)
    assert outro.tabela.rowCount() == 0
    window.close()


def test_abrir_o_resultado_carrega_o_pdf_na_janela(qtbot, a, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    carregados = []
    monkeypatch.setattr(window, '_load_file', carregados.append)
    dialogo = window._criar_dialogo_juntar()
    qtbot.addWidget(dialogo)
    dialogo.abrir_resultado.emit(str(a))
    assert carregados == [str(a)]
    window.close()
