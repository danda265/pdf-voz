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


@pytest.fixture
def blank_page_pdf(tmp_path):
    """PDF de uma pagina sem nenhum texto — caso de borda do extrator de spans."""
    path = tmp_path / 'blank.pdf'
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def multipage_pdf(tmp_path):
    """PDF de 3 paginas, cada uma com texto proprio — exercita navegacao entre paginas."""
    path = tmp_path / 'multipage.pdf'
    doc = fitz.open()
    for numero in (1, 2, 3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f'Pagina numero {numero}', fontsize=14, fontname='helv', color=(0, 0, 0))
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def subset_font_pdf(tmp_path):
    """PDF com fonte embutida como subset, do jeito que Word/Distiller geram.

    Esse subset costuma vir sem mapeamento unicode utilizavel: reusa-lo para escrever
    texto novo desenha caixinhas (.notdef) no lugar das letras."""
    import os
    times = r'C:\Windows\Fonts\times.ttf'
    if not os.path.exists(times):
        pytest.skip('Times New Roman nao encontrada em C:/Windows/Fonts')
    path = tmp_path / 'subset.pdf'
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_font(fontname='F1', fontfile=times)
    page.insert_text((72, 100), 'conteudo estabelece o tom', fontsize=12, fontname='F1')
    doc.subset_fonts()
    doc.save(str(path))
    doc.close()
    return path
