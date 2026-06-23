from __future__ import annotations

import sys
from pathlib import Path


def _tesseract_cmd() -> str:
    """Retorna o caminho do tesseract.exe — embutido no exe ou instalado no sistema."""
    # Quando empacotado pelo PyInstaller, sys._MEIPASS aponta para a pasta de dados
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    bundled = base / 'tesseract' / 'tesseract.exe'
    if bundled.exists():
        return str(bundled)
    # Fallback: Tesseract instalado no sistema
    system_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ]
    for p in system_paths:
        if Path(p).exists():
            return p
    return 'tesseract'  # espera estar no PATH


def _tessdata_dir() -> str:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    bundled = base / 'tesseract' / 'tessdata'
    if bundled.exists():
        return str(bundled)
    return ''


def ocr_pdf_page(page, zoom: float = 2.0, language: str = 'por') -> str:
    """Executa OCR em uma página do PyMuPDF sem texto selecionável usando Tesseract embutido."""
    try:
        import fitz
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise RuntimeError('Dependência OCR ausente.') from exc

    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd()

    tessdata = _tessdata_dir()
    config = f'--tessdata-dir "{tessdata}"' if tessdata else ''

    matrix  = fitz.Matrix(zoom, zoom)
    pixmap  = page.get_pixmap(matrix=matrix, alpha=False)
    from io import BytesIO
    image = Image.open(BytesIO(pixmap.tobytes('png')))
    return pytesseract.image_to_string(image, lang=language, config=config).strip()
