"""Texto de paginas que sao so imagem: reconhecido por OCR e devolvido como texto editavel.

Num PDF feito de imagens (slides exportados como figura, paginas escaneadas) nao ha texto nem
forma para aproveitar: so pixels. O que da para recuperar com seguranca e o texto comum, que o
OCR le e que sai da imagem, deixando o fundo no lugar. O resto continua imagem:

  - texto miudo (dentro de capturas de tela), pouco confiavel para o OCR;
  - texto estilizado ou sobre foto: apagar da imagem estragaria o desenho ao redor, entao so
    se apaga onde o fundo e liso o bastante para ser refeito sem se notar.

Cada palavra mantem a cor e o negrito que tinha, e linhas de mesmo tamanho uma sob a outra
viram um paragrafo so. O OCR erra (letras parecidas, palavras coladas): o texto reconhecido
precisa de revisao.
"""
from __future__ import annotations

import os
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageFilter, ImageFont

import ocr as _ocr

IDIOMAS = 'por'                  # so portugues: com 'por+eng' o OCR perdia metade dos acentos (as, numeros)
CONFIANCA_MINIMA = 72            # abaixo disso o OCR provavelmente leu errado
ALTURA_MINIMA = 0.014            # fracao da altura da imagem: menor que isso e miudo demais
LARGURA_MINIMA_PX = 1200         # imagens menores sao ampliadas antes do OCR
LIMIAR_NEGRITO = 0.14            # espessura do traco / altura da letra: acima disso e negrito
LIMIAR_NEGRITO_VIZINHA = 0.115   # ... e esse, para a vizinha de uma palavra em negrito da mesma cor
_MARGEM = 4                      # px entre a area apagada e a faixa de onde se le o fundo
_RUGOSIDADE_MAXIMA = 22          # variacao da faixa de fundo acima disso = nao e liso
_SIMBOLOS = set('*%º°ª—–|•·»«>~_=+#@©®')
_FONTES = {False: r'C:\Windows\Fonts\arial.ttf', True: r'C:\Windows\Fonts\arialbd.ttf'}

Cor = Tuple[int, int, int]


@dataclass
class Palavra:
    texto: str
    x0: int
    y0: int
    x1: int
    y1: int


@dataclass
class Trecho:
    """Pedaco de texto com um estilo so (cor e negrito)."""
    texto: str
    cor: Cor = (0, 0, 0)
    negrito: bool = False
    quebra_antes: bool = False   # comeca uma nova linha do paragrafo (quebra manual, como no original)


@dataclass
class Linha:
    texto: str
    x0: int
    y0: int
    x1: int
    y1: int
    maior_palavra: int        # altura da palavra mais alta: o melhor indicio do tamanho da letra
    confianca: float
    palavras: List[Palavra] = field(default_factory=list)
    trechos: List[Trecho] = field(default_factory=list)
    negrito: bool = False     # a maior parte das letras e em negrito
    tamanho_px: float = 0.0   # maior Arial cujo texto cabe na largura da linha

    @property
    def altura(self) -> int:
        return self.y1 - self.y0

    @property
    def largura(self) -> int:
        return self.x1 - self.x0


@dataclass
class Paragrafo:
    linhas: List[Linha]
    centralizado: bool = False
    tamanho_px: float = 0.0           # tamanho da fonte, em px da imagem
    passo_px: float = 0.0             # distancia entre linhas (so com mais de uma)

    @property
    def texto(self) -> str:
        return ' '.join(l.texto for l in self.linhas)

    @property
    def caixa(self) -> Tuple[int, int, int, int]:
        return (min(l.x0 for l in self.linhas), min(l.y0 for l in self.linhas),
                max(l.x1 for l in self.linhas), max(l.y1 for l in self.linhas))

    @property
    def negrito(self) -> bool:
        negritas = sum(len(l.texto) for l in self.linhas if l.negrito)
        return negritas * 2 > sum(len(l.texto) for l in self.linhas)

    @property
    def trechos(self) -> List[Trecho]:
        """Os trechos de todas as linhas em sequencia; cada linha nova marca uma quebra manual.

        A quebra fica onde estava no original: deixar o PowerPoint reflui-las mudaria os
        lugares das quebras (a fonte de troca tem outra largura)."""
        resultado: List[Trecho] = []
        for i, linha in enumerate(self.linhas):
            for j, t in enumerate(linha.trechos):
                resultado.append(Trecho(t.texto, t.cor, t.negrito, quebra_antes=(i > 0 and j == 0)))
        return resultado


@dataclass
class ResultadoOCR:
    imagem: Image.Image                           # a imagem com o texto reconhecido apagado
    paragrafos: List[Paragrafo] = field(default_factory=list)
    linhas_ignoradas: int = 0                     # lidas pelo OCR mas deixadas na imagem


def tesseract_disponivel() -> bool:
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = _ocr._tesseract_cmd()
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# ── Leitura ──────────────────────────────────────────────────────────────────

def _le_linhas(imagem: Image.Image, fator: float) -> List[Linha]:
    """Linhas lidas pelo OCR, com as coordenadas ja divididas por `fator` (se a imagem foi ampliada)."""
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _ocr._tesseract_cmd()
    pasta = _ocr._tessdata_dir()
    if pasta:
        os.environ['TESSDATA_PREFIX'] = pasta
    # --psm 11: texto esparso, sem supor colunas: o que combina com slides e cartazes
    dados = pytesseract.image_to_data(imagem, lang=IDIOMAS, config='--psm 11',
                                      output_type=pytesseract.Output.DICT)
    agrupadas: dict = {}
    for i, texto in enumerate(dados['text']):
        if not texto.strip() or float(dados['conf'][i]) < 0:
            continue
        chave = (dados['block_num'][i], dados['par_num'][i], dados['line_num'][i])
        agrupadas.setdefault(chave, []).append(
            (texto, dados['left'][i], dados['top'][i], dados['width'][i], dados['height'][i],
             float(dados['conf'][i])))
    linhas = []
    for palavras in agrupadas.values():
        palavras = _sem_marcadores(sorted(palavras, key=lambda p: p[1]))
        if not palavras:
            continue
        caixas = [Palavra(p[0], int(p[1] / fator), int(p[2] / fator), int((p[1] + p[3]) / fator),
                          int((p[2] + p[4]) / fator)) for p in palavras]
        linhas.append(Linha(
            texto=' '.join(p[0] for p in palavras),
            x0=min(c.x0 for c in caixas), y0=min(c.y0 for c in caixas),
            x1=max(c.x1 for c in caixas), y1=max(c.y1 for c in caixas),
            maior_palavra=int(max(p[4] for p in palavras) / fator),
            confianca=sum(p[5] for p in palavras) / len(palavras), palavras=caixas))
    return linhas


def _sem_marcadores(palavras: List[tuple]) -> List[tuple]:
    """Tira das pontas da linha o que o OCR leu de icones e marcadores (O, *, Q, º...).

    Um marcador vem separado do texto por um vao maior que o de um espaco, e e curto ou so
    simbolo. Sem isso, o icone de um monitor virava um 'Q' no texto e sumia da imagem."""
    palavras = list(palavras)
    while len(palavras) > 1:
        altura = max(p[4] for p in palavras)
        for ponta, vizinha in ((palavras[0], palavras[1]), (palavras[-1], palavras[-2])):
            miolo = ''.join(c for c in ponta[0] if c.isalnum())
            if ponta is palavras[0]:
                vao = abs(vizinha[1] - (ponta[1] + ponta[3]))
            else:
                vao = abs(ponta[1] - (vizinha[1] + vizinha[3]))
            so_simbolo = bool(ponta[0]) and all(c in _SIMBOLOS for c in ponta[0])
            curta_e_afastada = len(miolo) <= 2 and vao > 0.6 * altura
            if so_simbolo or curta_e_afastada:
                palavras.remove(ponta)
                break
        else:
            return palavras
    return palavras


def _vale_a_pena(linha: Linha, altura_imagem: int) -> bool:
    letras = sum(c.isalnum() for c in linha.texto)
    return (linha.confianca >= CONFIANCA_MINIMA and letras >= 3
            and letras / max(1, len(linha.texto.replace(' ', ''))) >= 0.7
            and linha.altura >= max(12, ALTURA_MINIMA * altura_imagem))


# ── Fundo ────────────────────────────────────────────────────────────────────

def _faixa(imagem: Image.Image, caixa: Tuple[int, int, int, int]) -> List[Cor]:
    dados = imagem.crop(caixa).tobytes()
    return [(dados[i], dados[i + 1], dados[i + 2]) for i in range(0, len(dados), 3)]


def _rugosidade(valores: Sequence[Cor]) -> float:
    """Quanto a faixa foge de uma reta entre suas pontas (0 = liso ou degrade suave)."""
    n = len(valores)
    if n < 3:
        return 0.0
    pior = 0.0
    for canal in range(3):
        a, b = valores[0][canal], valores[-1][canal]
        desvios = sorted(abs(valores[i][canal] - (a + (b - a) * i / (n - 1))) for i in range(n))
        pior = max(pior, desvios[int(0.95 * (n - 1))])
    return pior


def _apaga_texto(imagem: Image.Image, caixa: Tuple[int, int, int, int], acima: int, abaixo: int) -> bool:
    """Refaz o fundo sob o texto a partir das faixas em volta; False se ele nao for liso.

    So troca os pixels de TINTA (e o halo deles) pelo fundo refeito, e olha alem da caixa do
    OCR — acentos, cedilhas e rabos de g e p passam dela. `acima` e `abaixo` limitam quanto
    se olha para cima e para baixo, para nao morder a linha vizinha. So mexe na imagem se o
    fundo em volta for liso e a area nao for mais tinta que fundo (nao e texto)."""
    x0, y0, x1, y1 = caixa
    x0, y0, x1, y1 = x0 - 4, y0 - acima, x1 + 4, y1 + abaixo
    if x0 - _MARGEM < 0 or y0 - _MARGEM < 0 or x1 + _MARGEM >= imagem.width or y1 + _MARGEM >= imagem.height:
        return False
    esquerda = _suaviza(_faixa(imagem, (x0 - _MARGEM, y0, x0 - _MARGEM + 1, y1)))
    direita = _suaviza(_faixa(imagem, (x1 + _MARGEM, y0, x1 + _MARGEM + 1, y1)))
    cima = _suaviza(_faixa(imagem, (x0, y0 - _MARGEM, x1, y0 - _MARGEM + 1)))
    baixo = _suaviza(_faixa(imagem, (x0, y1 + _MARGEM, x1, y1 + _MARGEM + 1)))
    if max(_rugosidade(f) for f in (esquerda, direita, cima, baixo)) > _RUGOSIDADE_MAXIMA:
        return False
    largura, altura = x1 - x0, y1 - y0
    lados_h = Image.new('RGB', (2, altura))
    lados_h.putdata([p for e, d in zip(esquerda, direita) for p in (e, d)])
    lados_v = Image.new('RGB', (largura, 2))
    lados_v.putdata(list(cima) + list(baixo))
    fundo = Image.blend(lados_h.resize((largura, altura), Image.BILINEAR),
                        lados_v.resize((largura, altura), Image.BILINEAR), 0.5)
    regiao = imagem.crop((x0, y0, x1, y1))
    r, g, b = ImageChops.difference(regiao, fundo).split()
    diferenca = ImageChops.lighter(ImageChops.lighter(r, g), b)
    tinta = diferenca.point(lambda v: 255 if v > 38 else 0)
    mascara = tinta.filter(ImageFilter.MaxFilter(5))            # o halo de serrilhado em volta da tinta
    if mascara.histogram()[255] > 0.6 * largura * altura:
        return False                                            # mais tinta que fundo: nao e texto
    imagem.paste(fundo, (x0, y0), mascara)
    return True


def _suaviza(valores: Sequence[Cor], janela: int = 7) -> List[Cor]:
    """Mediana movel: some com o risco isolado de uma letra vizinha que cruza a faixa de fundo."""
    n, meio = len(valores), janela // 2
    if n < janela:
        return list(valores)
    resultado = []
    for i in range(n):
        trecho = valores[max(0, i - meio):i + meio + 1]
        resultado.append(tuple(sorted(v[c] for v in trecho)[len(trecho) // 2] for c in range(3)))
    return resultado


# ── Estilo ───────────────────────────────────────────────────────────────────

def _distancia(p: Cor, q: Cor) -> int:
    return abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2])


def estilo_da_palavra(original: Image.Image, limpa: Image.Image, p: Palavra) -> Optional[Tuple[Cor, float]]:
    """(cor da tinta, espessura media do traco em px) comparando a imagem com o fundo refeito."""
    caixa = (p.x0, p.y0, p.x1, p.y1)
    largura, altura = p.x1 - p.x0, p.y1 - p.y0
    antes, depois = _faixa(original, caixa), _faixa(limpa, caixa)
    if not antes or largura < 2 or altura < 2:
        return None
    distancias = [_distancia(a, b) for a, b in zip(antes, depois)]
    topo = sorted(distancias)[int(0.97 * (len(distancias) - 1))]
    if topo < 90:
        return None
    firme = [d >= 0.6 * topo for d in distancias]
    tinta = [a for a, f in zip(antes, firme) if f]
    cor = tuple(int(statistics.median(px[c] for px in tinta)) for c in range(3))
    # espessura = area / (perimetro / 2): pixels de tinta com algum vizinho sem tinta formam a borda
    mascara = [d >= 0.45 * topo for d in distancias]
    area = borda = 0
    for y in range(altura):
        for x in range(largura):
            if not mascara[y * largura + x]:
                continue
            area += 1
            vizinhos = ((x > 0 and mascara[y * largura + x - 1]), (x < largura - 1 and mascara[y * largura + x + 1]),
                        (y > 0 and mascara[(y - 1) * largura + x]), (y < altura - 1 and mascara[(y + 1) * largura + x]))
            if not all(vizinhos):
                borda += 1
    return cor, (2.0 * area / borda if borda else 0.0)


def _monta_trechos(linha: Linha, original: Image.Image, limpa: Image.Image) -> None:
    """Estilo por palavra: palavras vizinhas com o mesmo estilo viram um trecho so."""
    estilos = []
    for palavra in linha.palavras:
        medido = estilo_da_palavra(original, limpa, palavra)
        estilos.append(medido if medido else (None, 0.0))
    # palavras sem tinta mensuravel herdam o estilo da vizinha mais proxima
    padrao = next(((c, d) for c, d in estilos if c is not None), ((0, 0, 0), 0.0))
    anterior = padrao
    for i, (cor, dens) in enumerate(estilos):
        if cor is None:
            estilos[i] = anterior
        else:
            anterior = (cor, dens)
    razoes = [esp / max(1, linha.maior_palavra) for _, esp in estilos]
    negritos = [r > LIMIAR_NEGRITO for r in razoes]
    # histerese: acentos e cedilhas distorcem a medida; quem quase chega, e e vizinha de negrito da
    # mesma cor, e do mesmo trecho
    for sentido in (range(1, len(negritos)), range(len(negritos) - 2, -1, -1)):
        for i in sentido:
            anterior = i - 1 if sentido.step > 0 else i + 1
            if (not negritos[i] and negritos[anterior] and razoes[i] > LIMIAR_NEGRITO_VIZINHA
                    and _distancia(estilos[i][0], estilos[anterior][0]) <= 60):
                negritos[i] = True
    for i in range(1, len(negritos) - 1):          # palavra curta isolada entre duas iguais: o estilo das vizinhas
        letras = sum(c.isalnum() for c in linha.palavras[i].texto)
        if letras <= 2 and negritos[i - 1] == negritos[i + 1] != negritos[i]:
            negritos[i] = negritos[i - 1]
    trechos: List[Trecho] = []
    caracteres_negrito = 0
    for palavra, (cor, _), negrito in zip(linha.palavras, estilos, negritos):
        if negrito:
            caracteres_negrito += len(palavra.texto)
        if trechos and trechos[-1].negrito == negrito and _distancia(trechos[-1].cor, cor) <= 60:
            trechos[-1].texto += ' ' + palavra.texto
        else:
            if trechos:
                trechos[-1].texto += ' '
            trechos.append(Trecho(palavra.texto, cor, negrito))
    linha.trechos = trechos
    linha.negrito = caracteres_negrito * 2 > sum(len(p.texto) for p in linha.palavras)


# ── Tamanho, paragrafos e alinhamento ────────────────────────────────────────

def _fonte_px(negrito: bool, tamanho: int):
    try:
        return ImageFont.truetype(_FONTES[negrito], tamanho)
    except OSError:
        return None


def _tamanho_da_linha(linha: Linha) -> float:
    """Maior tamanho de Arial cujo texto cabe na largura que a linha tem na imagem."""
    por_altura = linha.maior_palavra / 0.70           # teto: caixa alta + descendente
    if _fonte_px(linha.negrito, 20) is None:
        return por_altura * 0.8
    lo, hi = 6, 600
    while hi - lo > 1:
        meio = (lo + hi) // 2
        if _fonte_px(linha.negrito, meio).getlength(linha.texto) <= linha.largura:
            lo = meio
        else:
            hi = meio
    return min(float(lo), por_altura)


def _junta_em_paragrafos(linhas: Sequence[Linha]) -> List[Paragrafo]:
    """Linhas uma embaixo da outra, do mesmo tamanho e alinhadas, formam um paragrafo."""
    paragrafos: List[Paragrafo] = []
    for linha in sorted(linhas, key=lambda l: (l.y0, l.x0)):
        destino = None
        for p in reversed(paragrafos):
            ultima = p.linhas[-1]
            h = max(ultima.maior_palavra, linha.maior_palavra)
            abaixo = linha.y0 > ultima.y0 + 0.4 * h
            folga = linha.y0 - ultima.y1
            parecidas = abs(linha.tamanho_px - ultima.tamanho_px) <= 0.12 * max(linha.tamanho_px, ultima.tamanho_px)
            alinhada = (abs(linha.x0 - ultima.x0) <= 0.7 * h
                        or abs((linha.x0 + linha.x1) - (ultima.x0 + ultima.x1)) <= 1.4 * h)
            if abaixo and -0.3 * h <= folga <= 0.9 * h and parecidas and alinhada:
                destino = p
                break
        if destino is None:
            paragrafos.append(Paragrafo([linha]))
        else:
            destino.linhas.append(linha)
    return paragrafos


def _ajusta_paragrafo(p: Paragrafo) -> None:
    p.tamanho_px = statistics.median(l.tamanho_px for l in p.linhas)
    if len(p.linhas) > 1:
        p.passo_px = statistics.median(b.y0 - a.y0 for a, b in zip(p.linhas, p.linhas[1:]))
        esquerdas = [l.x0 for l in p.linhas]
        centros = [(l.x0 + l.x1) / 2 for l in p.linhas]
        p.centralizado = (max(esquerdas) - min(esquerdas)) > 2 * (max(centros) - min(centros)) + 4


def _espaco_vertical(linha: Linha, todas: Sequence[Linha]) -> Tuple[int, int]:
    """Quanto se pode apagar para cima e para baixo da linha sem alcancar a linha vizinha.

    O OCR mede a linha sem a ponta dos acentos e dos rabos de g, p e q: ~20% acima e ~40% abaixo
    da altura da linha cobrem isso, desde que nao entrem na linha de cima ou de baixo."""
    desejo_acima, desejo_abaixo = round(0.20 * linha.altura), round(0.40 * linha.altura)
    acima, abaixo = desejo_acima, desejo_abaixo
    for outra in todas:
        if outra is linha or outra.x1 < linha.x0 or outra.x0 > linha.x1:
            continue                                   # nao esta na mesma coluna
        if outra.y0 >= linha.y1 - 2:
            abaixo = min(abaixo, max(2, outra.y0 - linha.y1 - 1))
        elif outra.y1 <= linha.y0 + 2:
            acima = min(acima, max(2, linha.y0 - outra.y1 - 1))
    return acima, abaixo


# ── Entrada ──────────────────────────────────────────────────────────────────

def reconhecer_e_limpar(imagem: Image.Image) -> ResultadoOCR:
    """Le o texto da imagem e devolve a imagem sem ele, mais os paragrafos para virar caixas."""
    base = imagem.convert('RGB')
    ampliada, fator = base, 1.0
    if base.width < LARGURA_MINIMA_PX:
        fator = LARGURA_MINIMA_PX / base.width
        ampliada = base.resize((LARGURA_MINIMA_PX, int(base.height * fator)), Image.LANCZOS)
    linhas = _le_linhas(ampliada, fator)

    candidatas = [l for l in linhas if _vale_a_pena(l, base.height)]
    ignoradas = len(linhas) - len(candidatas)
    limpa = base.copy()
    aceitas: List[Linha] = []
    pendentes = list(candidatas)
    for _ in range(3):                  # as recusadas voltam depois que as vizinhas ja foram limpas
        recusadas = []
        for linha in pendentes:
            ficam = [l for l in linhas if not any(l is a for a in aceitas)]
            acima, abaixo = _espaco_vertical(linha, ficam)
            if _apaga_texto(limpa, (linha.x0, linha.y0, linha.x1, linha.y1), acima, abaixo):
                aceitas.append(linha)
            else:
                recusadas.append(linha)
        if len(recusadas) == len(pendentes):
            break
        pendentes = recusadas
    ignoradas += len(pendentes)
    for linha in aceitas:               # acabamento: rabos de g, p e cedilhas que a vizinha ainda escondia
        ficam = [l for l in linhas if not any(l is a for a in aceitas)]
        acima, abaixo = _espaco_vertical(linha, ficam)
        _apaga_texto(limpa, (linha.x0, linha.y0, linha.x1, linha.y1), acima, abaixo)
    for linha in aceitas:
        _monta_trechos(linha, base, limpa)
        linha.tamanho_px = _tamanho_da_linha(linha)
    paragrafos = _junta_em_paragrafos(aceitas)
    for paragrafo in paragrafos:
        _ajusta_paragrafo(paragrafo)
    return ResultadoOCR(limpa, paragrafos, ignoradas)
