from __future__ import annotations

import fitz
import pytest


@pytest.fixture
def sample_pdf(tmp_path):
    path = tmp_path / 'sample.pdf'
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), 'Ola mundo', fontsize=14, fontname='helv', color=(0, 0, 0))
    page.insert_text((72, 140), 'Segunda linha de teste', fontsize=12, fontname='helv', color=(0, 0, 0))
    doc.save(str(path))
    doc.close()
    return path
