from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from pdf_reader import PDFReader
from utils import clean_text, ensure_supported_file
from word_reader import WordReader


@dataclass
class ReadResult:
    text: str
    total_pages: int
    kind: str
    pages: List[str] = field(default_factory=list)  # texto por página (só PDF); vazio para Word


class DocumentReader:
    def __init__(self, use_ocr: bool = True):
        self.use_ocr = use_ocr

    def read(self, path: str, progress_callback: Optional[Callable[[int, int], None]] = None) -> ReadResult:
        file_path = ensure_supported_file(path)
        suffix = file_path.suffix.lower()
        if suffix == '.pdf':
            # páginas já vêm limpas do PDFReader — não re-limpar para manter os limites de página
            result = PDFReader(use_ocr=self.use_ocr).read(str(file_path), progress_callback)
            return ReadResult(result.text, result.total_pages, 'PDF', result.pages)
        result = WordReader().read(str(file_path))
        if progress_callback:
            progress_callback(1, 1)
        return ReadResult(clean_text(result.text), result.total_pages, 'Word', [])
