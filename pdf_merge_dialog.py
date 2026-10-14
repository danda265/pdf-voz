"""Janela "Juntar PDFs": lista de arquivos, ordem e paginas de cada um."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from pdf_merge import (
    EntradaJuntar, JuntarCancelado, JuntarError, ResultadoJuncao, contar_paginas, juntar_pdfs,
    paginas_da_selecao,
)
from utils import sanitize_error_message

_COL_ARQUIVO, _COL_TOTAL, _COL_PAGINAS = 0, 1, 2
_FUNDO_ERRO, _TEXTO_ERRO = QColor('#FECACA'), QColor('#7F1D1D')


@dataclass
class _Item:
    caminho: str
    total: int
    paginas: str = ''   # selecao digitada pelo usuario; '' = todas


class JuntarThread(QThread):
    progress = pyqtSignal(int, int)
    done     = pyqtSignal(object)   # ResultadoJuncao
    error    = pyqtSignal(str)

    def __init__(self, entradas: List[EntradaJuntar], destino: str):
        super().__init__()
        self.entradas = entradas
        self.destino  = destino
        self._cancelar = threading.Event()

    def cancelar(self) -> None:
        self._cancelar.set()

    def _avanco(self, atual: int, total: int) -> None:
        self.progress.emit(atual, total)
        if self._cancelar.is_set():
            raise JuntarCancelado()

    def run(self) -> None:
        try:
            self.done.emit(juntar_pdfs(self.entradas, self.destino, self._avanco))
        except JuntarCancelado:
            pass
        except JuntarError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(sanitize_error_message(str(exc)))


class JuntarDialog(QDialog):
    abrir_resultado = pyqtSignal(str)   # caminho do PDF juntado, quando o usuario pede para abri-lo

    def __init__(self, parent=None, pasta_inicial: str = '', arquivo_aberto: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle('Juntar PDFs')
        self.setMinimumSize(660, 440)
        self.resize(760, 500)
        self.setAcceptDrops(True)
        self._pasta = pasta_inicial or str(Path.home())
        self._itens: List[_Item] = []
        self._thread: Optional[JuntarThread] = None
        self._build_ui()
        if arquivo_aberto and Path(arquivo_aberto).suffix.lower() == '.pdf':
            self._adicionar_caminhos([arquivo_aberto])
        self._atualizar()

    # ── Interface ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 18, 20, 18)
        raiz.setSpacing(12)

        dica = QLabel(
            'Adicione os PDFs (ou arraste-os para cá) e ajuste a ordem com ▲ e ▼. '
            'Para usar só parte de um arquivo, escreva as páginas na última coluna, '
            'por exemplo: <b>1-3, 5, 8-</b>. Em branco, o arquivo entra inteiro.'
        )
        dica.setWordWrap(True)
        raiz.addWidget(dica)

        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeaderLabels(['Arquivo', 'Páginas do arquivo', 'Quais páginas usar'])
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                    | QAbstractItemView.EditTrigger.SelectedClicked
                                    | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setAlternatingRowColors(True)
        cabecalho = self.tabela.horizontalHeader()
        cabecalho.setSectionResizeMode(_COL_ARQUIVO, QHeaderView.ResizeMode.Stretch)
        cabecalho.setSectionResizeMode(_COL_TOTAL, QHeaderView.ResizeMode.ResizeToContents)
        cabecalho.setSectionResizeMode(_COL_PAGINAS, QHeaderView.ResizeMode.Interactive)
        self.tabela.setColumnWidth(_COL_PAGINAS, 200)
        self.tabela.itemSelectionChanged.connect(self._atualizar)
        self.tabela.cellChanged.connect(self._ao_editar)
        raiz.addWidget(self.tabela, 1)

        linha = QHBoxLayout()
        self.botao_adicionar = QPushButton('Adicionar PDFs...')
        self.botao_remover = QPushButton('Remover')
        self.botao_subir = QPushButton('▲ Subir')
        self.botao_descer = QPushButton('▼ Descer')
        for botao in (self.botao_adicionar, self.botao_remover, self.botao_subir, self.botao_descer):
            botao.setMinimumHeight(32)
            linha.addWidget(botao)
        linha.addStretch(1)
        raiz.addLayout(linha)
        self.botao_adicionar.clicked.connect(self._escolher_arquivos)
        self.botao_remover.clicked.connect(self._remover)
        self.botao_subir.clicked.connect(lambda: self._mover(-1))
        self.botao_descer.clicked.connect(lambda: self._mover(+1))
        # so vale com a tabela em foco: com uma celula em edicao, Delete apaga letra, nao o arquivo
        atalho = QShortcut(QKeySequence.StandardKey.Delete, self.tabela, activated=self._remover)
        atalho.setContext(Qt.ShortcutContext.WidgetShortcut)

        self.resumo = QLabel()
        raiz.addWidget(self.resumo)
        self.progresso = QProgressBar()
        self.progresso.setTextVisible(False)
        self.progresso.setVisible(False)
        raiz.addWidget(self.progresso)

        base = QHBoxLayout()
        base.addStretch(1)
        self.botao_cancelar = QPushButton('Cancelar')
        self.botao_cancelar.setMinimumHeight(38)
        self.botao_juntar = QPushButton('Juntar e salvar...')
        self.botao_juntar.setObjectName('BtnRead')
        base.addWidget(self.botao_cancelar)
        base.addWidget(self.botao_juntar)
        raiz.addLayout(base)
        self.botao_cancelar.clicked.connect(self.reject)
        self.botao_juntar.clicked.connect(self._juntar)

    # ── Lista ─────────────────────────────────────────────────────────────────

    def _adicionar_caminhos(self, caminhos: List[str]) -> List[str]:
        """Acrescenta os PDFs validos ao fim da lista e devolve a mensagem de cada recusado."""
        problemas: List[str] = []
        for caminho in caminhos:
            try:
                total = contar_paginas(caminho)
            except JuntarError as exc:
                problemas.append(str(exc))
                continue
            self._itens.append(_Item(str(Path(caminho)), total))
            self._pasta = str(Path(caminho).parent)
        self._redesenhar(len(self._itens) - 1 if self._itens else None)
        return problemas

    def _escolher_arquivos(self) -> None:
        caminhos, _ = QFileDialog.getOpenFileNames(self, 'Escolher PDFs', self._pasta, 'PDF (*.pdf)')
        if caminhos:
            self._avisar_problemas(self._adicionar_caminhos(caminhos))

    def _avisar_problemas(self, problemas: List[str]) -> None:
        if problemas:
            QMessageBox.warning(self, 'Alguns arquivos ficaram de fora', '\n\n'.join(problemas))

    def _remover(self) -> None:
        linha = self.tabela.currentRow()
        if self._ocupado() or not 0 <= linha < len(self._itens):
            return
        del self._itens[linha]
        self._redesenhar(min(linha, len(self._itens) - 1) if self._itens else None)

    def _mover(self, delta: int) -> None:
        linha = self.tabela.currentRow()
        destino = linha + delta
        if self._ocupado() or not (0 <= linha < len(self._itens) and 0 <= destino < len(self._itens)):
            return
        self._itens[linha], self._itens[destino] = self._itens[destino], self._itens[linha]
        self._redesenhar(destino)

    def _redesenhar(self, selecionar: Optional[int] = None) -> None:
        self.tabela.blockSignals(True)
        self.tabela.setRowCount(len(self._itens))
        for linha, item in enumerate(self._itens):
            nome = QTableWidgetItem(Path(item.caminho).name)
            nome.setToolTip(item.caminho)
            nome.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            total = QTableWidgetItem(str(item.total))
            total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            total.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            paginas = QTableWidgetItem(item.paginas)
            paginas.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                             | Qt.ItemFlag.ItemIsEditable)
            self.tabela.setItem(linha, _COL_ARQUIVO, nome)
            self.tabela.setItem(linha, _COL_TOTAL, total)
            self.tabela.setItem(linha, _COL_PAGINAS, paginas)
        self.tabela.blockSignals(False)
        if selecionar is not None and 0 <= selecionar < len(self._itens):
            self.tabela.selectRow(selecionar)
        self._atualizar()

    def _ao_editar(self, linha: int, coluna: int) -> None:
        if coluna == _COL_PAGINAS and 0 <= linha < len(self._itens):
            self._itens[linha].paginas = self.tabela.item(linha, coluna).text()
            self._atualizar()

    # ── Estado ────────────────────────────────────────────────────────────────

    def _ocupado(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _erro_da_selecao(self, item: _Item) -> Optional[str]:
        try:
            paginas_da_selecao(item.paginas, item.total)
        except JuntarError as exc:
            return str(exc)
        return None

    def _atualizar(self) -> None:
        """Pinta as selecoes invalidas, refaz o resumo e liga ou desliga os botoes."""
        ocupado = self._ocupado()
        total_paginas, com_erro = 0, []
        self.tabela.blockSignals(True)
        for linha, item in enumerate(self._itens):
            celula = self.tabela.item(linha, _COL_PAGINAS)
            if celula is None:
                continue
            erro = self._erro_da_selecao(item)
            if erro:
                com_erro.append(Path(item.caminho).name)
                celula.setBackground(_FUNDO_ERRO)
                celula.setForeground(_TEXTO_ERRO)
                celula.setToolTip(erro)
            else:
                total_paginas += len(paginas_da_selecao(item.paginas, item.total))
                celula.setData(Qt.ItemDataRole.BackgroundRole, None)
                celula.setData(Qt.ItemDataRole.ForegroundRole, None)
                celula.setToolTip('Ex.: 1-3, 5, 8-   (em branco = todas)')
        self.tabela.blockSignals(False)

        if not self._itens:
            self.resumo.setText('Nenhum arquivo ainda.')
        elif com_erro:
            self.resumo.setText('Corrija as páginas de: ' + ', '.join(com_erro))
        else:
            arquivos = len(self._itens)
            self.resumo.setText(
                f'{arquivos} arquivo{"s" if arquivos != 1 else ""}  •  '
                f'{total_paginas} página{"s" if total_paginas != 1 else ""} no resultado')

        linha = self.tabela.currentRow()
        tem_linha = 0 <= linha < len(self._itens)
        self.botao_adicionar.setEnabled(not ocupado)
        self.botao_remover.setEnabled(not ocupado and tem_linha)
        self.botao_subir.setEnabled(not ocupado and tem_linha and linha > 0)
        self.botao_descer.setEnabled(not ocupado and tem_linha and linha < len(self._itens) - 1)
        self.tabela.setEnabled(not ocupado)
        self.botao_juntar.setEnabled(not ocupado and bool(self._itens) and not com_erro)

    # ── Juntar ────────────────────────────────────────────────────────────────

    def _sugestao_de_saida(self) -> str:
        pasta = Path(self._itens[0].caminho).parent if self._itens else Path(self._pasta)
        alvo, contador = pasta / 'juntado.pdf', 2
        while alvo.exists():
            alvo = pasta / f'juntado_{contador}.pdf'
            contador += 1
        return str(alvo)

    def _juntar(self) -> None:
        if not self._itens:
            return
        destino, _ = QFileDialog.getSaveFileName(
            self, 'Salvar PDF juntado', self._sugestao_de_saida(), 'PDF (*.pdf)')
        if not destino:
            return
        if not destino.lower().endswith('.pdf'):
            destino += '.pdf'
        self._iniciar(destino)

    def _iniciar(self, destino: str) -> None:
        entradas = [EntradaJuntar(i.caminho, i.paginas) for i in self._itens]
        self.progresso.setValue(0)
        self.progresso.setVisible(True)
        self._thread = JuntarThread(entradas, destino)
        self._thread.progress.connect(self._ao_progredir)
        self._thread.done.connect(self._concluido)
        self._thread.error.connect(self._falhou)
        self._thread.finished.connect(self._terminou)
        self._thread.start()
        self._atualizar()

    def _ao_progredir(self, atual: int, total: int) -> None:
        self.progresso.setValue(int(atual / max(total, 1) * 100))
        self.resumo.setText(f'Juntando: arquivo {atual} de {total}...')

    def _concluido(self, resultado: ResultadoJuncao) -> None:
        texto = (f'PDF salvo com {resultado.paginas} página{"s" if resultado.paginas != 1 else ""} '
                 f'(de {resultado.arquivos} arquivo{"s" if resultado.arquivos != 1 else ""}):\n\n'
                 f'{resultado.destino}')
        if self._perguntar_se_abre(texto):
            self.abrir_resultado.emit(resultado.destino)
        self.accept()

    def _perguntar_se_abre(self, texto: str) -> bool:
        caixa = QMessageBox(self)
        caixa.setIcon(QMessageBox.Icon.Information)
        caixa.setWindowTitle('PDF juntado')
        caixa.setText(texto)
        abrir = caixa.addButton('Abrir no PDF VOZ', QMessageBox.ButtonRole.AcceptRole)
        caixa.addButton('Fechar', QMessageBox.ButtonRole.RejectRole)
        caixa.exec()
        return caixa.clickedButton() is abrir

    def _falhou(self, mensagem: str) -> None:
        self.progresso.setVisible(False)
        QMessageBox.critical(self, 'Não foi possível juntar', mensagem)

    def _terminou(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        self.progresso.setVisible(False)
        self._atualizar()

    def done(self, resultado: int) -> None:
        """Fechar a janela no meio da juncao cancela: nada e gravado se nao chegou ao fim."""
        if self._thread is not None:
            self._thread.cancelar()
            self._thread.wait(5000)
        super().done(resultado)

    # ── Arrastar e soltar ─────────────────────────────────────────────────────

    @staticmethod
    def _pdfs_do_arraste(evento) -> List[str]:
        if not evento.mimeData().hasUrls():
            return []
        return [u.toLocalFile() for u in evento.mimeData().urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith('.pdf')]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not self._ocupado() and self._pdfs_do_arraste(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        caminhos = self._pdfs_do_arraste(event)
        if caminhos and not self._ocupado():
            event.acceptProposedAction()
            self._avisar_problemas(self._adicionar_caminhos(caminhos))
