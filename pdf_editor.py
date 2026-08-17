from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import fitz

Color = Tuple[float, float, float]


@dataclass
class TextSpan:
    text: str
    bbox: Tuple[float, float, float, float]
    origin: Tuple[float, float]
    font_name: str
    size: float
    color: Color
    bold: bool
    italic: bool
    serifed: bool


# Alinhamentos aceitos em FormatOverride.alinhamento. None = mantém onde está.
ALINHAMENTOS = {
    'esquerda': fitz.TEXT_ALIGN_LEFT,
    'centro': fitz.TEXT_ALIGN_CENTER,
    'direita': fitz.TEXT_ALIGN_RIGHT,
    'justificado': fitz.TEXT_ALIGN_JUSTIFY,
}


@dataclass
class FormatOverride:
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    size: Optional[float] = None
    color: Optional[Color] = None
    family: Optional[str] = None
    alinhamento: Optional[str] = None   # chave de ALINHAMENTOS; None = posição original
    entrelinha: Optional[float] = None  # multiplicador do tamanho da fonte (1.0, 1.5, 2.0...)


@dataclass
class FontChoice:
    fontname: str
    fontbuffer: Optional[bytes]
    size: float
    color: Color
    used_fallback: bool
    overflowed: bool = False   # o texto novo ocupou mais espaço vertical que o trecho original


def _int_to_rgb(value: int) -> Color:
    r = ((value >> 16) & 255) / 255
    g = ((value >> 8) & 255) / 255
    b = (value & 255) / 255
    return (r, g, b)


def spans_for_page(page: fitz.Page) -> List[TextSpan]:
    spans: List[TextSpan] = []
    raw = page.get_text('dict')
    for block in raw.get('blocks', []):
        for line in block.get('lines', []):
            for s in line.get('spans', []):
                flags = s.get('flags', 0)
                spans.append(TextSpan(
                    text=s['text'],
                    bbox=tuple(s['bbox']),
                    origin=tuple(s['origin']),
                    font_name=s['font'],
                    size=float(s['size']),
                    color=_int_to_rgb(s['color']),
                    bold=bool(flags & (1 << 4)),
                    italic=bool(flags & (1 << 1)),
                    serifed=bool(flags & (1 << 2)),
                ))
    return spans


_SERIF_HINTS = ('times', 'georgia', 'garamond', 'serif', 'cambria', 'book')
_BASE14_SANS = {(False, False): 'helv', (False, True): 'heit', (True, False): 'hebo', (True, True): 'hebi'}
_BASE14_SERIF = {(False, False): 'tiro', (False, True): 'tiit', (True, False): 'tibo', (True, True): 'tibi'}


def familia_legivel(font_name: str) -> str:
    """Nome de familia apresentavel a partir do nome bruto que o PDF traz.

    O PDF guarda a fonte com prefixo de subset e sufixo de estilo — 'ABCDEF+Calibri-Bold',
    'Times New Roman Regular', 'ArialMT'. Esses nomes nao casam com nenhuma fonte instalada,
    entao o seletor cairia num padrao qualquer. Aqui viram 'Calibri', 'Times New Roman',
    'Arial', que o sistema reconhece."""
    nome = re.sub(r'^[A-Z]{6}\+', '', font_name or '')
    nome = re.split(r'[-,]', nome)[0]
    nome = re.sub(r'(PSMT|MT|PS)$', '', nome)
    nome = re.sub(r'\s+(Regular|Bold|Italic|Oblique|Light|Medium|Black)$', '', nome, flags=re.I)
    return nome.strip() or font_name


def _normalize_family(name: str) -> dict:
    base = re.sub(r'^[A-Z]{6}\+', '', name)
    lowered = base.lower()
    bold = 'bold' in lowered
    italic = 'italic' in lowered or 'oblique' in lowered
    root = re.sub(r'(bold|italic|oblique|regular|mt|ps)', '', lowered)
    root = re.sub(r'[^a-z0-9]', '', root)
    return {'root': root, 'bold': bold, 'italic': italic}


def _embedded_font_buffer(doc: fitz.Document, page: fitz.Page, family_hint: Optional[str],
                           bold: bool, italic: bool) -> Tuple[Optional[str], Optional[bytes]]:
    if not family_hint:
        return None, None
    target = _normalize_family(family_hint)['root']
    for xref, _ext, _ftype, basefont, name, _encoding in page.get_fonts():
        for candidate in (basefont, name):
            norm = _normalize_family(candidate)
            if norm['root'] != target or norm['bold'] != bold or norm['italic'] != italic:
                continue
            try:
                info = doc.extract_font(xref)
            except Exception:
                continue
            buffer = info[-1] if info else None
            if buffer:
                return f'EF{xref}', buffer
    return None, None


# Fontes do Windows cujo arquivo nao se chama como a familia
_ALIAS_ARQUIVO = {
    'timesnewroman': 'times',
    'couriernew': 'cour',
    'lucidaconsole': 'lucon',
    'comicsansms': 'comic',
    'trebuchetms': 'trebuc',
    'palatinolinotype': 'pala',
    'bookantiqua': 'bkant',
    'centurygothic': 'gothic',
}

# Sufixos de estilo no nome do arquivo: arial/arialbd/ariali/arialbi, calibri/calibrib/.../calibriz
_SUFIXOS_ESTILO = {
    (False, False): ('',),
    (True,  False): ('bd', 'b'),
    (False, True):  ('i',),
    (True,  True):  ('bi', 'z'),
}


def _fonte_do_sistema(family: str, bold: bool, italic: bool) -> Optional[Tuple[str, bytes]]:
    """Carrega a fonte instalada correspondente a familia pedida.

    Sem isso, escolher 'Calibri' na lista entregaria Helvetica: o motor so tinha as 14
    fontes embutidas do PDF como alternativa. Aqui a fonte real do sistema e usada."""
    raiz = re.sub(r'[^a-z0-9]', '', (family or '').lower())
    if not raiz:
        return None
    raiz = _ALIAS_ARQUIVO.get(raiz, raiz)
    pasta = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    for sufixo in _SUFIXOS_ESTILO[(bold, italic)]:
        for extensao in ('.ttf', '.otf'):
            caminho = pasta / f'{raiz}{sufixo}{extensao}'
            if not caminho.is_file():
                continue
            try:
                dados = caminho.read_bytes()
            except OSError:
                continue
            return f'SYS{raiz}{sufixo}', dados
    return None


def _desenha_o_texto(fontbuffer: bytes, text: str) -> bool:
    """A fonte embutida consegue mesmo desenhar este texto?

    PDFs de Word/Distiller embutem a fonte como *subset*, muitas vezes sem tabela de
    mapeamento unicode utilizavel. Reusar uma dessas para escrever texto novo desenha
    caixinhas vazias no lugar das letras. Checar antes evita entregar isso ao usuario —
    quando nao cobre, o chamador cai no fallback e avisa 'fonte aproximada'."""
    if not text:
        return True
    try:
        fonte = fitz.Font(fontbuffer=fontbuffer)
    except Exception:
        return False
    return all(fonte.has_glyph(ord(ch)) for ch in text if not ch.isspace())


def resolve_font(doc: fitz.Document, page: fitz.Page, span: Optional[TextSpan],
                  override: Optional[FormatOverride], text: str = '') -> FontChoice:
    override = override or FormatOverride()
    bold = override.bold if override.bold is not None else (span.bold if span else False)
    italic = override.italic if override.italic is not None else (span.italic if span else False)
    size = override.size if override.size is not None else (span.size if span else 12.0)
    color = override.color if override.color is not None else (span.color if span else (0.0, 0.0, 0.0))
    family_hint = override.family if override.family else (span.font_name if span else None)

    # 1º: a propria fonte embutida no PDF — e a unica que reproduz o visual exato.
    fontname, fontbuffer = _embedded_font_buffer(doc, page, family_hint, bold, italic)
    if fontbuffer and _desenha_o_texto(fontbuffer, text):
        return FontChoice(fontname, fontbuffer, size, color, used_fallback=False)

    # 2º: a fonte instalada no sistema com o mesmo nome — visualmente equivalente.
    do_sistema = _fonte_do_sistema(familia_legivel(family_hint or ''), bold, italic)
    if do_sistema and _desenha_o_texto(do_sistema[1], text):
        return FontChoice(do_sistema[0], do_sistema[1], size, color, used_fallback=False)

    # 3º: base14 — sempre funciona, mas so aproxima o desenho da letra.
    if span is not None and not override.family:
        serifed = span.serifed
    else:
        serifed = any(hint in (family_hint or '').lower() for hint in _SERIF_HINTS)
    base14 = (_BASE14_SERIF if serifed else _BASE14_SANS)[(bold, italic)]
    # Carrega o proprio arquivo da fonte em vez de citar o nome: se a pagina ja tiver um
    # recurso com esse nome, o PyMuPDF reusa o dela, cujas metricas nao batem com as que
    # usamos para posicionar — e o texto desce ~1,6 pt em relacao a linha original.
    try:
        return FontChoice(f'PV{base14}', fitz.Font(base14).buffer, size, color,
                          used_fallback=True)
    except Exception:
        return FontChoice(base14, None, size, color, used_fallback=True)


def area_de_conteudo(page: fitz.Page) -> fitz.Rect:
    """Retangulo que envolve todo o texto da pagina — a "mancha" do documento.

    E a referencia para alinhar: centralizar tem de ser em relacao a area util onde o
    documento escreve, nao a folha inteira (senao um texto com margens largas ficaria
    visivelmente torto em relacao ao resto)."""
    uniao = None
    for bloco in page.get_text('dict').get('blocks', []):
        if not bloco.get('lines'):
            continue
        r = fitz.Rect(bloco['bbox'])
        uniao = r if uniao is None else uniao | r
    return uniao if uniao is not None else fitz.Rect(page.rect)


def _metricas_da_caixa(choice: FontChoice, entrelinha: Optional[float]) -> Tuple[float, float]:
    """(altura de uma linha, folga fixa) que o insert_textbox consome.

    Medido: a caixa precisa de `n * (asc - desc) * tamanho + |desc| * tamanho`. Usar um
    chute menor que isso faz ate um texto de uma linha "nao caber", a caixa crescer e o
    app acusar transbordo que nao existe."""
    asc, desc = _metricas_da_fonte(choice)
    altura_linha = choice.size * (entrelinha if entrelinha else (asc - desc))
    return altura_linha, abs(desc) * choice.size


def _metricas_da_fonte(choice: FontChoice) -> Tuple[float, float]:
    """(ascendente, descendente) da fonte escolhida, como fracao do tamanho."""
    try:
        fonte = (fitz.Font(fontbuffer=choice.fontbuffer) if choice.fontbuffer
                 else fitz.Font(choice.fontname))
        return float(fonte.ascender), float(fonte.descender)
    except Exception:
        return 1.0, -0.3


def _ascendente(choice: FontChoice) -> float:
    """Fracao do tamanho da fonte acima da linha de base.

    Medido: o insert_textbox coloca a primeira linha de base exatamente em
    `rect.y0 + ascender * tamanho`. Ancorar por essa conta (e nao pelo topo do bbox
    antigo) mantem o texto no lugar mesmo quando a fonte nova tem altura diferente da
    original — que e o caso sempre que o motor cai no substituto."""
    return _metricas_da_fonte(choice)[0]


def _caixa_do_texto(page: fitz.Page, span: TextSpan, choice: FontChoice,
                    alinhamento: Optional[str], deslocamento: Tuple[float, float],
                    entrelinha: Optional[float] = None,
                    conteudo: Optional[fitz.Rect] = None) -> fitz.Rect:
    """Retangulo onde o texto novo sera escrito.

    Sem alinhamento escolhido, a caixa comeca na posicao original do trecho — assim o
    texto cai exatamente onde estava. Com alinhamento, ela ocupa a largura da mancha do
    documento, que e o que faz "centralizar" e "justificar" baterem com o resto da pagina.

    `conteudo` deve ser medido ANTES da redacao: apagar os trechos selecionados encolhe a
    mancha, e alinhar pela mancha encolhida jogaria o texto para o lugar errado."""
    conteudo = conteudo if conteudo is not None else area_de_conteudo(page)
    x0 = span.bbox[0] if alinhamento in (None, '') else min(conteudo.x0, span.bbox[0])
    x1 = max(conteudo.x1, span.bbox[2])
    altura_linha, folga = _metricas_da_caixa(choice, entrelinha)
    topo = span.origin[1] - _ascendente(choice) * choice.size
    return fitz.Rect(x0 + deslocamento[0], topo + deslocamento[1],
                     x1 + deslocamento[0], topo + altura_linha + folga + deslocamento[1])


def _escrever_na_caixa(page: fitz.Page, caixa: fitz.Rect, texto: str, choice: FontChoice,
                       alinhamento: Optional[str], entrelinha: Optional[float]) -> Tuple[bool, int]:
    """Escreve dentro da caixa, crescendo-a para baixo ate o texto caber.

    O insert_textbox NAO escreve nada quando o texto nao cabe (retorna negativo) — com a
    redacao ja aplicada, aceitar isso apagaria o trecho sem por nada no lugar. Por isso
    cresce e tenta de novo, mas nunca alem do fim da pagina: passar dali escreveria texto
    invisivel, que e pior que um erro claro. Devolve (coube, linhas_a_mais)."""
    alvo = fitz.Rect(caixa)
    altura_linha, folga = _metricas_da_caixa(choice, entrelinha)
    limite = page.rect.y1 - 2
    while True:
        sobra = page.insert_textbox(
            alvo, texto, fontname=choice.fontname, fontsize=choice.size,
            color=choice.color, align=ALINHAMENTOS.get(alinhamento or '', fitz.TEXT_ALIGN_LEFT),
            lineheight=entrelinha,
        )
        if sobra >= 0:
            # o que o texto de fato ocupou, descontada a folga fixa da caixa
            usado = max(0.0, (alvo.height - sobra) - folga)
            return True, max(1, round(usado / altura_linha))
        if alvo.y1 >= limite:
            return False, 0
        # sobra negativa = exatamente quanto faltou de altura
        alvo.y1 = min(limite, alvo.y1 + (-sobra) + altura_linha)


def replace_span_text(doc: fitz.Document, page: fitz.Page, span: TextSpan, new_text: str,
                      override: Optional[FormatOverride] = None,
                      deslocamento: Tuple[float, float] = (0.0, 0.0)) -> FontChoice:
    """Troca o texto de um span. `deslocamento` move o texto em relacao a posicao original
    (pontos do PDF). `new_text` pode conter '\\n' para quebra forcada; o texto tambem quebra
    sozinho ao chegar na borda da caixa. Alinhamento e entrelinha vem do `override`."""
    return replace_spans_text(doc, page, [span], [new_text], override, deslocamento)[0]


def replace_spans_text(doc: fitz.Document, page: fitz.Page, spans: List[TextSpan],
                       textos: List[str], override: Optional[FormatOverride] = None,
                       deslocamento: Tuple[float, float] = (0.0, 0.0)) -> List[FontChoice]:
    """Troca varios trechos de uma vez — cada um mantendo a PROPRIA formatacao.

    So o que veio preenchido no `override` (porque o usuario mexeu naquele controle) e
    aplicado a todos; o resto de cada trecho continua como estava. Alinhamento, entrelinha
    e deslocamento valem para o conjunto."""
    override = override or FormatOverride()
    # A mancha e medida antes de qualquer redacao: apagar os trechos selecionados a
    # encolheria, e alinhar por ela depois jogaria o texto para o lugar errado.
    conteudo = area_de_conteudo(page)
    # As fontes sao resolvidas ANTES de redigir: resolver le fontes embutidas e pode
    # falhar. Redigindo primeiro, uma falha aqui deixaria os trechos apagados sem
    # substituto — texto perdido. Falhando antes, a pagina fica intacta.
    escolhas = [resolve_font(doc, page, span, override, texto) if texto else None
                for span, texto in zip(spans, textos)]

    for span in spans:
        page.add_redact_annot(fitz.Rect(span.bbox), fill=(1, 1, 1))
    page.apply_redactions()

    resultado: List[FontChoice] = []
    for span, texto, choice in zip(spans, textos, escolhas):
        if not texto:
            resultado.append(FontChoice('', None, span.size, span.color, used_fallback=False))
            continue
        if choice.fontbuffer:
            page.insert_font(fontname=choice.fontname, fontbuffer=choice.fontbuffer)
        caixa = _caixa_do_texto(page, span, choice, override.alinhamento, deslocamento,
                                override.entrelinha, conteudo)
        coube, linhas = _escrever_na_caixa(page, caixa, texto, choice,
                                           override.alinhamento, override.entrelinha)
        if not coube:
            raise PDFEditError(
                'O texto novo não coube na página. Encurte o texto ou reduza o tamanho da fonte.'
            )
        choice.overflowed = linhas > 1
        resultado.append(choice)
    return resultado


def insert_free_text(doc: fitz.Document, page: fitz.Page, point: Tuple[float, float],
                      text: str, override: FormatOverride) -> FontChoice:
    choice = resolve_font(doc, page, None, override, text)
    if choice.fontbuffer:
        page.insert_font(fontname=choice.fontname, fontbuffer=choice.fontbuffer)
    page.insert_text(point, text, fontname=choice.fontname, fontsize=choice.size, color=choice.color)
    return choice


class PDFEditError(Exception):
    pass


def open_for_edit(path: str) -> fitz.Document:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise PDFEditError(f'Nao foi possivel abrir o PDF: {exc}') from exc
    if doc.is_encrypted:
        doc.close()
        raise PDFEditError('Este PDF e protegido por senha e nao pode ser editado.')
    if not doc.permissions & fitz.PDF_PERM_MODIFY:
        doc.close()
        raise PDFEditError('Este PDF nao permite edicao (restricao de permissao do arquivo).')
    return doc


class EditSession:
    def __init__(self, doc: fitz.Document):
        self.doc = doc
        self._undo_stack: List[bytes] = []

    def snapshot(self) -> None:
        self._undo_stack.append(self.doc.tobytes())

    def discard_last_snapshot(self) -> None:
        if self._undo_stack:
            self._undo_stack.pop()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        data = self._undo_stack.pop()
        self.doc.close()
        self.doc = fitz.open(stream=data, filetype='pdf')
        return True


def save_copy(doc: fitz.Document, original_path: str) -> Path:
    original = Path(original_path)
    target = original.with_name(f'{original.stem}_editado{original.suffix}')
    counter = 2
    while target.exists():
        target = original.with_name(f'{original.stem}_editado_{counter}{original.suffix}')
        counter += 1
    doc.save(str(target))
    return target
