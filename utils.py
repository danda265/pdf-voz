import re
import unicodedata
from pathlib import Path
from typing import List

SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.doc'}
MAX_FILE_MB = 100.0

# Ligaduras e invisíveis — chaves como ord() evitam qualquer ambiguidade de encoding
_LIGATURES = str.maketrans({
    0xFB01: 'fi',   # ﬁ
    0xFB02: 'fl',   # ﬂ
    0xFB03: 'ffi',  # ﬃ
    0xFB04: 'ffl',  # ﬄ
    0xFB00: 'ff',   # ﬀ
    0xFB05: 'ft',   # ﬅ
    0xFB06: 'st',   # ﬆ
    0x00A0: ' ',    # espaço não-separável (comum em PDF de Word) → espaço normal
    0x00AD: None,   # soft hyphen
    0x200B: None,   # zero-width space
    0x200C: None,   # zero-width non-joiner
    0xFEFF: None,   # BOM
})

# Pontuação tipográfica → amigável ao TTS
_PUNCT = str.maketrans({
    0x2014: ', ',   # — travessão
    0x2013: ', ',   # – meia-risca
    0x2026: '...',  # … reticências
    0x201C: '"',    # “ aspas esq.
    0x201D: '"',    # ” aspas dir.
    0x2018: "'",    # ‘ apóstrofo esq.
    0x2019: "'",    # ’ apóstrofo dir.
})


def clean_text(text: str) -> str:
    if not text:
        return ''

    # 1. NFC: junta base + acento combinado em um único caractere (é, ã, ç, etc.)
    text = unicodedata.normalize('NFC', text)

    # 2. Ligaduras e caracteres invisíveis
    text = text.translate(_LIGATURES)

    # 3. Pontuação tipográfica → amigável ao TTS
    text = text.translate(_PUNCT)

    # 4. Quebra de linha com hífen de parágrafo: "pro-\ncesso" → "processo"
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)

    # 5. Normalização de quebras de linha
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[\t\f\v]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ ]{2,}', ' ', text)

    # 6. Pontuação colada
    text = re.sub(r' +([,.;:!?%])', r'\1', text)
    # separa "fim.Próximo" -> "fim. Próximo", mas preserva "..." e "3.14"
    text = re.sub(r'([,.;:!?])(?=[^\W\d_])', r'\1 ', text)
    text = re.sub(r'\s+\n', '\n', text)

    return text.strip()


def sanitize_error_message(msg: str) -> str:
    """Remove caminhos internos de mensagens de erro antes de exibi-las."""
    msg = re.sub(r'[A-Za-z]:\\(?:[^\s"\'<>|*?\n]+\\)*[^\s"\'<>|*?\n]*', '[arquivo]', msg)
    msg = re.sub(r'(?:/[\w.\-]+){2,}', '[arquivo]', msg)
    return msg[:400] if len(msg) > 400 else msg


def split_text(text: str, max_chars: int = 2600) -> List[str]:
    text = clean_text(text)
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    chunks: List[str] = []
    current = ''

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ''

    for paragraph in paragraphs:
        sentences = re.split(r'(?<=[.!?;:])\s+', paragraph)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > max_chars:
                flush()
                for start in range(0, len(sentence), max_chars):
                    chunks.append(sentence[start:start + max_chars].strip())
                continue
            candidate = f'{current} {sentence}'.strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                flush()
                current = sentence
        if current and len(current) + 2 <= max_chars:
            current += '\n\n'
        else:
            flush()
    flush()
    return [chunk for chunk in chunks if chunk]


def ensure_supported_file(path: str) -> Path:
    file_path = Path(path).resolve()
    if not file_path.exists():
        raise FileNotFoundError('Arquivo não encontrado.')
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError('Formato não suportado. Use PDF, DOCX ou DOC.')
    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise ValueError(f'Arquivo muito grande ({size_mb:.1f} MB). Limite: {MAX_FILE_MB:.0f} MB.')
    return file_path


def temp_audio_name(index: int) -> str:
    return f'leitura_bloco_{index:05d}.mp3'
