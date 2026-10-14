"""Conversao de PDF para PowerPoint (.pptx), sem dependencia de interface.

Dois modos:
  - MODO_IMAGEM: cada pagina vira um slide com a pagina inteira como imagem. Fiel ao PDF, mas
    nada nele e editavel.
  - MODO_EDITAVEL: o slide e remontado com objetos do PowerPoint — o texto horizontal vira
    caixas de texto (mesma posicao, fonte, tamanho e cor), as formas do PDF viram formas
    (retangulos, elipses, linhas, curvas) e as fotos viram imagens soltas, tudo na ordem de
    empilhamento do PDF. O que o PDF nao descreve como forma (degrades, sombreados) ou nao da
    para separar com seguranca (foto recortada em canto redondo) fica como imagem de fundo.

O PDF original nunca e alterado: as remocoes de texto acontecem so na copia em memoria.
"""
from __future__ import annotations

import math
import os
import re
import struct
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from statistics import median
from typing import Callable, List, Optional, Tuple

import fitz
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.util import Emu, Pt

from pdf_editor import _fonte_do_sistema, familia_legivel
from pdf_to_pptx_objetos import (
    AnaliseDaPagina, Forma, Posicao, Recorte, adicionar_figura, adicionar_forma, analisar_pagina,
    pixels_diferentes, redesenhar,
)

MODO_IMAGEM = 'imagem'
MODO_EDITAVEL = 'editavel'

# Resolucao do fundo de cada slide. O modo editavel usa menos porque o texto sai da imagem.
_DPI = {MODO_IMAGEM: 200, MODO_EDITAVEL: 150}
_LADO_MAXIMO_PX = 4000          # trava de memoria para paginas enormes (cartazes)
_EMU_POR_PT = 12700
_SLIDE_MAX_PT = 4000            # o PowerPoint nao aceita slide acima de 56 pol (4032 pt)
_SLIDE_MIN_PT = 72              # ... nem abaixo de 1 pol
_CONTROLE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

ProgressCallback = Optional[Callable[[int, int], None]]


class ConversaoError(Exception):
    """Falha esperada da conversao, com mensagem que pode ir direto para o usuario."""


class ConversaoCancelada(Exception):
    """O chamador interrompeu a conversao (levantada de dentro do progress_callback).

    Nenhum arquivo de saida e criado: o pptx so e gravado depois da ultima pagina."""


@dataclass
class ResultadoConversao:
    destino: str
    paginas: int
    caixas_de_texto: int = 0
    paginas_sem_texto_editavel: int = 0   # no modo editavel: paginas sem nenhum texto virando caixa
    formas: int = 0                       # formas do PDF recriadas como objetos do slide
    imagens: int = 0                      # imagens do PDF recriadas como objetos do slide
    paginas_com_parte_em_imagem: int = 0  # paginas em que algo ficou como imagem de fundo


@dataclass
class _Linha:
    bbox: Tuple[float, float, float, float]
    baseline: float
    spans: List[dict]


def _limpa(texto: str) -> str:
    # caracteres de controle quebram o XML do pptx
    return _CONTROLE.sub('', texto)


def _tamanho_do_slide(pagina: fitz.Rect) -> Tuple[float, float]:
    """Tamanho do slide em pontos: o da primeira pagina, ajustado ao que o PowerPoint aceita."""
    largura, altura = pagina.width, pagina.height
    escala = 1.0
    if max(largura, altura) > _SLIDE_MAX_PT:
        escala = _SLIDE_MAX_PT / max(largura, altura)
    if min(largura, altura) * escala < _SLIDE_MIN_PT:
        escala = _SLIDE_MIN_PT / min(largura, altura)
    return largura * escala, altura * escala


def _encaixe(pagina: fitz.Rect, slide: Tuple[float, float]) -> Tuple[float, float, float]:
    """Escala e deslocamento (em pt do slide) que colocam a pagina inteira dentro do slide."""
    escala = min(slide[0] / pagina.width, slide[1] / pagina.height)
    return (escala,
            (slide[0] - pagina.width * escala) / 2,
            (slide[1] - pagina.height * escala) / 2)


def _emu(valor_pt: float) -> Emu:
    return Emu(int(round(valor_pt * _EMU_POR_PT)))


def _imagem_da_pagina(page: fitz.Page, dpi: int, pular_se_em_branco: bool = False) -> Optional[BytesIO]:
    """Renderiza a pagina. JPEG quando ha foto (PNG ficaria enorme), PNG nos demais.
    Com `pular_se_em_branco`, devolve None para pagina sem nada desenhado."""
    maior_lado_pt = max(page.rect.width, page.rect.height)
    dpi = max(36, min(dpi, int(_LADO_MAXIMO_PX / maior_lado_pt * 72)))
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    if pular_se_em_branco and _em_branco(pix):
        return None
    if page.get_images():
        return BytesIO(pix.tobytes('jpeg', jpg_quality=88))
    return BytesIO(pix.tobytes('png'))


def _caixas_invisiveis(page: fitz.Page) -> List[fitz.Rect]:
    """Areas com texto invisivel — a camada de OCR dos PDFs escaneados.

    Esse texto fica por cima da imagem do scan sem aparecer; virar caixa de texto o tornaria
    visivel e duplicado."""
    try:
        trace = page.get_texttrace()
    except Exception:
        return []
    return [fitz.Rect(t['bbox']) for t in trace if t.get('type') == 3]


def _linhas_editaveis(page: fitz.Page) -> List[List[_Linha]]:
    """Blocos de texto horizontal e visivel da pagina, cada um com suas linhas."""
    invisiveis = _caixas_invisiveis(page)
    blocos: List[List[_Linha]] = []
    for bloco in page.get_text('dict').get('blocks', []):
        if bloco.get('type') != 0:
            continue
        linhas: List[_Linha] = []
        for linha in bloco.get('lines', []):
            direcao = linha.get('dir', (1, 0))
            if abs(direcao[1]) > 0.01 or direcao[0] < 0:   # girado ou de tras para frente
                continue
            spans = [s for s in linha.get('spans', []) if _limpa(s.get('text', '')).strip()]
            if not spans:
                continue
            bbox = fitz.Rect(linha['bbox'])
            centro = fitz.Point((bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2)
            if any(centro in area for area in invisiveis):
                continue
            linhas.append(_Linha(tuple(bbox), spans[0]['origin'][1], spans))
        if linhas:
            blocos.append(linhas)
    return blocos


def _tamanho_da_linha(linha: _Linha) -> float:
    return max(s['size'] for s in linha.spans)


def _grupos_de_linhas(linhas: List[_Linha]) -> List[List[_Linha]]:
    """Linhas que alinham na esquerda e tem o mesmo tamanho formam um paragrafo so (uma caixa).

    As demais — centralizadas, ou de tamanhos diferentes como um titulo colado no subtitulo —
    ficam cada uma na sua caixa: o espaçamento exato de uma caixa so serve a linhas parecidas,
    e em linhas desiguais empurraria a primeira para baixo."""
    if len(linhas) > 1:
        alinhadas = max(l.bbox[0] for l in linhas) - min(l.bbox[0] for l in linhas) <= 2.0
        tamanhos = [_tamanho_da_linha(l) for l in linhas]
        if alinhadas and max(tamanhos) <= min(tamanhos) * 1.15:
            return [linhas]
    return [[l] for l in linhas]


def _aplica_span(run, span: dict, escala: float) -> None:
    run.text = _limpa(span['text'])
    fonte = run.font
    fonte.name = familia_legivel(span.get('font', '')) or 'Arial'
    fonte.size = Pt(max(1.0, span['size'] * escala))
    flags = span.get('flags', 0)
    nome = (span.get('font') or '').lower()
    fonte.bold = bool(flags & 16) or 'bold' in nome
    fonte.italic = bool(flags & 2) or 'italic' in nome or 'oblique' in nome
    cor = span.get('color', 0)
    fonte.color.rgb = RGBColor((cor >> 16) & 255, (cor >> 8) & 255, cor & 255)


def _metricas_win(dados: bytes) -> Optional[Tuple[float, float]]:
    """Ascendente e descendente (em fracao do tamanho) que o Windows usa para a fonte (OS/2 win)."""
    try:
        quantidade = struct.unpack('>H', dados[4:6])[0]
        tabelas = {}
        for i in range(quantidade):
            tag, _, inicio, _ = struct.unpack('>4sIII', dados[12 + 16 * i:28 + 16 * i])
            tabelas[tag] = inicio
        upem = struct.unpack('>H', dados[tabelas[b'head'] + 18:tabelas[b'head'] + 20])[0]
        asc, desc = struct.unpack('>HH', dados[tabelas[b'OS/2'] + 74:tabelas[b'OS/2'] + 78])
        return (asc / upem, desc / upem) if upem and asc + desc else None
    except (KeyError, struct.error, ZeroDivisionError):
        return None


@lru_cache(maxsize=256)
def _ascendente_do_powerpoint(familia: str, negrito: bool, italico: bool) -> Optional[float]:
    """Quanto da altura da fonte fica acima da linha de base numa linha do PowerPoint.

    A linha simples do PowerPoint mede 1,2 vezes o tamanho, dividida na proporcao
    ascendente/descendente da fonte. Sem isso, uma caixa posta pelo topo da linha do PDF cai
    em lugares diferentes conforme a fonte (Calibri 18% mais baixo, Segoe UI 11% mais alto).
    Medido contra o PowerPoint em 9 fontes: erro de ate 2,4% do tamanho."""
    achada = _fonte_do_sistema(familia, negrito, italico)
    metricas = _metricas_win(achada[1]) if achada else None
    return 1.2 * metricas[0] / (metricas[0] + metricas[1]) if metricas else None


def _ascendente_da_linha(linha: _Linha) -> float:
    """Distancia, em pontos do PDF, da linha de base ao topo da caixa que o PowerPoint espera."""
    maior = 0.0
    for span in linha.spans:
        flags = span.get('flags', 0)
        nome = (span.get('font') or '').lower()
        negrito = bool(flags & 16) or 'bold' in nome
        italico = bool(flags & 2) or 'italic' in nome or 'oblique' in nome
        fracao = _ascendente_do_powerpoint(familia_legivel(span.get('font', '')), negrito, italico)
        if fracao is None:       # fonte nao instalada: usa as medidas da propria fonte do PDF
            asc, desc = span.get('ascender') or 0.9, span.get('descender') or -0.2
            fracao = 1.2 * asc / (asc - desc)
        maior = max(maior, fracao * span['size'])
    return maior


def _adiciona_caixa(slide, grupo: List[_Linha], escala: float, dx: float, dy: float) -> None:
    x0 = min(l.bbox[0] for l in grupo)
    y0 = grupo[0].baseline - _ascendente_da_linha(grupo[0])   # topo que poe a linha de base no lugar
    x1 = max(l.bbox[2] for l in grupo)
    y1 = max(max(l.bbox[3] for l in grupo), y0 + 1)
    caixa = slide.shapes.add_textbox(_emu(dx + x0 * escala), _emu(dy + y0 * escala),
                                     _emu((x1 - x0) * escala), _emu((y1 - y0) * escala))
    quadro = caixa.text_frame
    quadro.margin_left = quadro.margin_right = quadro.margin_top = quadro.margin_bottom = 0
    quadro.word_wrap = False           # as quebras de linha sao as do PDF, nao do PowerPoint
    quadro.auto_size = MSO_AUTO_SIZE.NONE
    quadro.vertical_anchor = MSO_ANCHOR.TOP
    passos = [b.baseline - a.baseline for a, b in zip(grupo, grupo[1:])]
    for indice, linha in enumerate(grupo):
        paragrafo = quadro.paragraphs[0] if indice == 0 else quadro.add_paragraph()
        if passos:
            paragrafo.line_spacing = Pt(median(passos) * escala)
        for span in linha.spans:
            _aplica_span(paragrafo.add_run(), span, escala)


def _remove_o_texto_horizontal(page: fitz.Page, blocos: List[List[_Linha]]) -> None:
    """Apaga da pagina (em memoria) o texto que vai virar caixa, sem encostar em fotos nem desenhos."""
    for bloco in blocos:
        for linha in bloco:
            rect = fitz.Rect(linha.bbox)
            folga = rect.height * 0.12     # nao invade a linha vizinha
            rect = fitz.Rect(rect.x0, rect.y0 + folga, rect.x1, rect.y1 - folga)
            page.add_redact_annot(rect, fill=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE)


def _remove_formas_e_imagens(page: fitz.Page) -> None:
    """Apaga da pagina (em memoria) todas as formas e imagens, que viram objetos do slide.
    O texto nao entra: o que nao virou caixa continua na imagem de fundo."""
    page.add_redact_annot(page.rect, fill=False)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE,
                          graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                          text=fitz.PDF_REDACT_TEXT_NONE)


def _em_branco(pix: fitz.Pixmap) -> bool:
    """Pixmap sem nada desenhado: totalmente transparente ou todo branco."""
    # contas feitas nos bytes: Pixmap.is_unicolor percorre pixel a pixel em Python (7 s por pagina)
    amostras = pix.samples
    if pix.alpha:
        return not amostras.lstrip(b'\x00')
    return amostras.count(b'\xff') == len(amostras)


def _cobre_a_pagina(desenho: dict, pagina: fitz.Rect) -> bool:
    """Retangulo liso e opaco do tamanho da pagina inteira: e o fundo do slide, nao uma forma."""
    itens = desenho['items']
    return (desenho['type'] == 'f' and desenho.get('fill') is not None
            and (desenho.get('fill_opacity') or 1) >= 0.999
            and len(itens) == 1 and itens[0][0] == 're'
            and abs(desenho['rect'][0] - pagina.x0) <= 1 and abs(desenho['rect'][1] - pagina.y0) <= 1
            and abs(desenho['rect'][2] - pagina.x1) <= 1 and abs(desenho['rect'][3] - pagina.y1) <= 1)


_DPI_CONFERENCIA = 60            # resolucao da conferencia por redesenho: barata, o que importa e a forma
_TOLERANCIA_CONFERENCIA = 0.0005  # fracao da pagina que pode diferir (so serrilhado) sem reprovar


def _ilhas_de_degrade(pagina: fitz.Page, recortes: List[Recorte],
                      dpi: int) -> List[Tuple[Recorte, fitz.Pixmap]]:
    """Degrades e sombreados: o PDF nao os descreve como forma, entao cada um vira uma imagem
    recortada da pagina so na area dele, no lugar certo da pilha. A redacao que tira as formas
    apaga tambem o degrade, por isso o recorte sai da pagina original."""
    zoom = dpi / 72
    ilhas: List[Tuple[Recorte, fitz.Pixmap]] = []
    for recorte in recortes:
        # alinha o recorte aos pixels: a imagem cobre exatamente a area em que sera colocada
        area = fitz.Rect(math.floor(recorte.caixa.x0 * zoom) / zoom, math.floor(recorte.caixa.y0 * zoom) / zoom,
                         math.ceil(recorte.caixa.x1 * zoom) / zoom, math.ceil(recorte.caixa.y1 * zoom) / zoom)
        area &= pagina.rect
        if area.is_empty:
            continue
        ilhas.append((Recorte(recorte.ordem, area), pagina.get_pixmap(dpi=dpi, alpha=False, clip=area)))
    return ilhas


def _em_ordem(analise: AnaliseDaPagina,
              cortes: List[Tuple[Recorte, fitz.Pixmap]]) -> List[Tuple[int, str, object]]:
    itens: List[Tuple[int, str, object]] = (
        [(f.ordem, 'forma', f) for f in analise.formas]
        + [(g.ordem, 'imagem', g) for g in analise.figuras]
        + [(r.ordem, 'recorte', (r, c)) for r, c in cortes])
    return sorted(itens, key=lambda i: i[0])


def _tenta_objetos(doc: fitz.Document, page: fitz.Page, analise: AnaliseDaPagina,
                   dpi: int) -> Optional[Tuple[Optional[fitz.Pixmap], List[Tuple[Recorte, fitz.Pixmap]]]]:
    """Confere se recriar as formas e imagens como objetos deixa a pagina igual ao PDF.

    Redesenha a pagina so com o que viraria objeto e compara com ela como esta (ja sem o texto
    que vira caixa). Se igual, devolve o fundo restante e as ilhas na resolucao final; se nao,
    None e a pagina continua como imagem. A pagina original nao e tocada: a remocao das formas
    acontece numa copia."""
    alvo = page.get_pixmap(dpi=_DPI_CONFERENCIA, alpha=False)
    copia = fitz.open()
    try:
        copia.insert_pdf(doc, from_page=page.number, to_page=page.number)
        _remove_formas_e_imagens(copia[0])
        restante = copia[0].get_pixmap(dpi=_DPI_CONFERENCIA, alpha=True)
        ilhas = _ilhas_de_degrade(page, analise.recortes, _DPI_CONFERENCIA)
        refeita = redesenhar(page.rect, None if _em_branco(restante) else restante,
                             [(t, o) for _, t, o in _em_ordem(analise, ilhas)], _DPI_CONFERENCIA)
        if pixels_diferentes(alvo, refeita) > max(30, int(_TOLERANCIA_CONFERENCIA * alvo.width * alvo.height)):
            return None
        # fundo restante vazio na conferencia = vazio tambem na resolucao final: poupa o render
        fundo = None if _em_branco(restante) else copia[0].get_pixmap(dpi=dpi, alpha=True)
        return fundo, _ilhas_de_degrade(page, analise.recortes, dpi)
    except Exception:
        return None          # qualquer surpresa do PDF: fica como imagem, que e o caminho seguro
    finally:
        copia.close()


def _monta_pagina_editavel(doc: fitz.Document, page: fitz.Page, slide, slide_pt: Tuple[float, float],
                           resultado: ResultadoConversao) -> None:
    escala, dx, dy = _encaixe(page.rect, slide_pt)
    pos = Posicao(escala, dx, dy)
    dpi = _DPI[MODO_EDITAVEL]
    girada = page.rotation != 0           # coordenadas de pagina girada nao batem com as da imagem
    analise = AnaliseDaPagina() if girada else analisar_pagina(doc, page)
    blocos = [] if girada else _linhas_editaveis(page)
    if not blocos:
        resultado.paginas_sem_texto_editavel += 1
    else:
        _remove_o_texto_horizontal(page, blocos)

    # formas e imagens so viram objetos se TODAS puderem e se o resultado ficar igual ao PDF:
    # um objeto solto por cima de uma imagem de fundo que ainda contem o resto esconderia
    # o que estava por baixo
    pronto = None
    if analise.formas_ok and analise.figuras_ok and (analise.formas or analise.figuras):
        pronto = _tenta_objetos(doc, page, analise, dpi)

    itens: List[Tuple[int, str, object]] = []
    fundo_solido = None
    imagem_de_fundo: Optional[BytesIO] = None
    parte_em_imagem = False
    if pronto is not None:
        restante, ilhas = pronto
        itens = _em_ordem(analise, ilhas)
        parte_em_imagem = bool(ilhas)
        primeiro = itens[0][2] if itens else None
        sem_encaixe = abs(dx) < 0.5 and abs(dy) < 0.5 and abs(escala - 1) < 1e-6
        if isinstance(primeiro, Forma) and sem_encaixe and _cobre_a_pagina(primeiro.desenho, page.rect):
            fundo_solido = primeiro.desenho['fill']
            itens = itens[1:]
        if restante is not None and not _em_branco(restante):
            imagem_de_fundo = BytesIO(restante.tobytes('png'))
    else:
        imagem_de_fundo = _imagem_da_pagina(page, dpi, pular_se_em_branco=True)
        parte_em_imagem = bool(analise.formas or analise.figuras)   # havia o que separar e nao deu
    parte_em_imagem = parte_em_imagem or imagem_de_fundo is not None

    if fundo_solido is not None:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(*(round(c * 255) for c in fundo_solido))
    if imagem_de_fundo is not None:               # o que nao virou objeto, por baixo de tudo
        slide.shapes.add_picture(imagem_de_fundo, _emu(dx), _emu(dy), _emu(page.rect.width * escala),
                                 _emu(page.rect.height * escala))
    if parte_em_imagem:
        resultado.paginas_com_parte_em_imagem += 1

    contagem = {'forma': 0, 'imagem': 0}
    for _, tipo, objeto in itens:
        if tipo == 'forma':
            contagem['forma'] += 1
            adicionar_forma(slide, objeto.desenho, pos, contagem['forma'])
            resultado.formas += 1
        elif tipo == 'imagem':
            contagem['imagem'] += 1
            adicionar_figura(slide, objeto, pos, contagem['imagem'])
            resultado.imagens += 1
        else:
            recorte, cortado = objeto
            contagem['imagem'] += 1
            figura = slide.shapes.add_picture(
                BytesIO(cortado.tobytes('png')), pos.x(recorte.caixa.x0), pos.y(recorte.caixa.y0),
                pos.comprimento(recorte.caixa.width), pos.comprimento(recorte.caixa.height))
            figura.name = f'Imagem {contagem["imagem"]} (degradê ou sombreado)'
    for bloco in blocos:
        for grupo in _grupos_de_linhas(bloco):
            _adiciona_caixa(slide, grupo, escala, dx, dy)
            resultado.caixas_de_texto += 1


def converter_pdf_para_pptx(origem: str, destino: str, modo: str = MODO_EDITAVEL,
                            progress_callback: ProgressCallback = None) -> ResultadoConversao:
    if modo not in (MODO_IMAGEM, MODO_EDITAVEL):
        raise ConversaoError('Modo de conversão desconhecido.')
    origem_p, destino_p = Path(origem), Path(destino)
    if origem_p.suffix.lower() != '.pdf' or not origem_p.is_file():
        raise ConversaoError('Abra um PDF válido para converter.')
    if destino_p.resolve() == origem_p.resolve():
        raise ConversaoError('O arquivo de saída não pode ser o próprio PDF.')

    try:
        doc = fitz.open(str(origem_p))
    except Exception as exc:
        raise ConversaoError(f'Não foi possível abrir o PDF: {exc}') from exc

    with doc:
        if doc.needs_pass:
            raise ConversaoError('O PDF está protegido por senha.')
        total = doc.page_count
        if total == 0:
            raise ConversaoError('O PDF não tem páginas.')

        slide_pt = _tamanho_do_slide(doc[0].rect)
        apresentacao = Presentation()
        apresentacao.slide_width = _emu(slide_pt[0])
        apresentacao.slide_height = _emu(slide_pt[1])
        layout_vazio = apresentacao.slide_layouts[6]
        resultado = ResultadoConversao(str(destino_p), total)

        for indice in range(total):
            page = doc[indice]
            slide = apresentacao.slides.add_slide(layout_vazio)
            if modo == MODO_EDITAVEL:
                _monta_pagina_editavel(doc, page, slide, slide_pt, resultado)
            else:
                escala, dx, dy = _encaixe(page.rect, slide_pt)
                slide.shapes.add_picture(_imagem_da_pagina(page, _DPI[modo]), _emu(dx), _emu(dy),
                                         _emu(page.rect.width * escala),
                                         _emu(page.rect.height * escala))
            if progress_callback:
                progress_callback(indice + 1, total)

    temporario = destino_p.with_name(destino_p.name + '.parcial')
    try:
        apresentacao.save(str(temporario))
        os.replace(temporario, destino_p)
    except OSError as exc:
        raise ConversaoError(f'Não foi possível salvar o arquivo (ele está aberto em outro programa?): {exc}') from exc
    finally:
        if temporario.exists():
            temporario.unlink()
    return resultado
