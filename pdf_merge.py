"""Juntar PDFs em um arquivo so, sem dependencia de interface.

Cada entrada e um PDF mais a selecao de paginas a usar ('' = todas; ou '1-3, 5, 8-'). As paginas
saem na ordem em que a selecao as lista, e os arquivos na ordem da lista de entradas. Os PDFs de
origem nunca sao alterados; o resultado so aparece no disco depois de a ultima pagina ser copiada.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import fitz

ProgressCallback = Optional[Callable[[int, int], None]]


class JuntarError(Exception):
    """Falha esperada, com mensagem que pode ir direto para o usuario."""


class JuntarCancelado(Exception):
    """O chamador interrompeu a juncao (levantada de dentro do progress_callback).

    Nenhum arquivo de saida e criado: o PDF so e gravado depois da ultima pagina."""


@dataclass
class EntradaJuntar:
    caminho: str
    paginas: str = ''   # '' = todas; senao '1-3, 5, 8-' (numeracao a partir de 1)


@dataclass
class ResultadoJuncao:
    destino: str
    arquivos: int
    paginas: int


_TOKEN = re.compile(r'^(\d*)\s*(-?)\s*(\d*)$')


def paginas_da_selecao(texto: str, total: int) -> List[int]:
    """Indices (a partir de 0) das paginas que a selecao pede, na ordem pedida.

    '' ou so espacos = todas. Aceita '3', '2-5', '8-' (ate o fim), '-3' (do inicio) e listas
    separadas por virgula ou ponto e virgula. Repetir uma pagina e permitido."""
    texto = (texto or '').strip()
    if not texto:
        return list(range(total))
    indices: List[int] = []
    for pedaco in re.split(r'[;,]', texto):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        achado = _TOKEN.match(pedaco)
        if not achado or not (achado.group(1) or achado.group(3)):
            raise JuntarError(f'Não entendi "{pedaco}". Use algo como 1-3, 5, 8-')
        inicio_txt, traco, fim_txt = achado.groups()
        if not traco:                       # pagina unica: '5'
            if inicio_txt and fim_txt:      # '5 5': dois numeros sem traco
                raise JuntarError(f'Não entendi "{pedaco}". Use algo como 1-3, 5, 8-')
            inicio = fim = int(inicio_txt or fim_txt)
        else:
            inicio = int(inicio_txt) if inicio_txt else 1
            fim = int(fim_txt) if fim_txt else total
        if inicio < 1 or fim < 1:
            raise JuntarError('As páginas começam em 1.')
        for numero in (inicio, fim):
            if numero > total:
                raise JuntarError(f'A página {numero} não existe (o arquivo tem {total}).')
        if inicio > fim:
            raise JuntarError(f'O intervalo {inicio}-{fim} está invertido.')
        indices.extend(range(inicio - 1, fim))
    if not indices:
        raise JuntarError('Nenhuma página escolhida.')
    return indices


def _abrir(caminho: str) -> fitz.Document:
    arquivo = Path(caminho)
    if arquivo.suffix.lower() != '.pdf' or not arquivo.is_file():
        raise JuntarError(f'"{arquivo.name}" não é um PDF que o app consiga abrir.')
    try:
        doc = fitz.open(str(arquivo))
    except Exception as exc:
        raise JuntarError(f'Não foi possível abrir "{arquivo.name}": {exc}') from exc
    if doc.needs_pass:
        doc.close()
        raise JuntarError(f'"{arquivo.name}" está protegido por senha.')
    if doc.page_count == 0:
        doc.close()
        raise JuntarError(f'"{arquivo.name}" não tem páginas.')
    return doc


def contar_paginas(caminho: str) -> int:
    """Total de paginas de um PDF, ou JuntarError dizendo por que nao serve."""
    with _abrir(caminho) as doc:
        return doc.page_count


def _trechos_continuos(indices: Sequence[int]) -> List[range]:
    """Agrupa indices em subsequencias crescentes de passo 1 (uma chamada de insert_pdf cada)."""
    trechos: List[range] = []
    for indice in indices:
        if trechos and trechos[-1].stop == indice:
            trechos[-1] = range(trechos[-1].start, indice + 1)
        else:
            trechos.append(range(indice, indice + 1))
    return trechos


def juntar_pdfs(entradas: Sequence[EntradaJuntar], destino: str,
                progress_callback: ProgressCallback = None) -> ResultadoJuncao:
    if not entradas:
        raise JuntarError('Adicione pelo menos um PDF.')
    destino_p = Path(destino)
    if destino_p.suffix.lower() != '.pdf':
        raise JuntarError('O arquivo de saída precisa terminar em .pdf.')
    destino_real = destino_p.resolve()
    for entrada in entradas:
        if Path(entrada.caminho).resolve() == destino_real:
            raise JuntarError('O arquivo de saída não pode ser um dos PDFs que estão sendo juntados.')

    resultado = fitz.open()
    try:
        total_paginas = 0
        for numero, entrada in enumerate(entradas, start=1):
            with _abrir(entrada.caminho) as origem:
                try:
                    indices = paginas_da_selecao(entrada.paginas, origem.page_count)
                except JuntarError as exc:
                    raise JuntarError(f'{Path(entrada.caminho).name}: {exc}') from exc
                for trecho in _trechos_continuos(indices):
                    resultado.insert_pdf(origem, from_page=trecho.start, to_page=trecho.stop - 1)
                total_paginas += len(indices)
            if progress_callback:
                progress_callback(numero, len(entradas))

        temporario = destino_p.with_name(destino_p.name + '.parcial')
        try:
            resultado.save(str(temporario), garbage=2, deflate=True)
            os.replace(temporario, destino_p)
        except OSError as exc:
            raise JuntarError(
                f'Não foi possível salvar o arquivo (ele está aberto em outro programa?): {exc}') from exc
        finally:
            if temporario.exists():
                temporario.unlink()
    finally:
        resultado.close()
    return ResultadoJuncao(str(destino_p), len(entradas), total_paginas)
