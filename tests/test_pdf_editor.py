from __future__ import annotations

import fitz

from pdf_editor import spans_for_page


def test_spans_for_page_extracts_text_and_position(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    spans = spans_for_page(doc[0])
    doc.close()
    texts = [s.text.strip() for s in spans]
    assert 'Ola mundo' in texts
    assert 'Segunda linha de teste' in texts
    first = next(s for s in spans if s.text.strip() == 'Ola mundo')
    assert first.size == 14.0
    assert first.bold is False
    assert first.italic is False
