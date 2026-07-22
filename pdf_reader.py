from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

import fitz

from ocr import ocr_pdf_page
from utils import clean_text

ProgressCallback = Optional[Callable[[int, int], None]]


@dataclass
class DocumentText:
    text: str
    total_pages: int
    pages: List[str] = field(default_factory=list)  # texto limpo por página; índice 0 = página 1


class PDFReader:
    def __init__(self, use_ocr: bool = True):
        self.use_ocr = use_ocr

    def read(self, path: str, progress_callback: ProgressCallback = None) -> DocumentText:
        pages_text: List[str] = []
        with fitz.open(path) as document:
            total = document.page_count
            for index, page in enumerate(document, start=1):
                text = page.get_text('text').strip()
                if not text and self.use_ocr:
                    try:
                        text = ocr_pdf_page(page)
                    except Exception as exc:
                        text = f'[Pagina {index}: OCR falhou — {exc}]'
                # cada página é limpa individualmente para poder ler a partir de qualquer uma
                pages_text.append(clean_text(f'--- Pagina {index} de {total} ---\n\n{text}'))
                if progress_callback:
                    progress_callback(index, total)
        return DocumentText('\n\n'.join(pages_text), total, pages_text)
