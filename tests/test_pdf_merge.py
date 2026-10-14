from __future__ import annotations

import fitz
import pytest

from pdf_merge import (
    EntradaJuntar, JuntarCancelado, JuntarError, contar_paginas, juntar_pdfs, paginas_da_selecao,
)


def _pdf(caminho, rotulo: str, paginas: int, largura: float = 595, altura: float = 842):
    """PDF em que a pagina N diz '<rotulo>-N', para conferir de onde cada pagina veio."""
    doc = fitz.open()
    for n in range(1, paginas + 1):
        doc.new_page(width=largura, height=altura).insert_text(
            (72, 100), f'{rotulo}-{n}', fontsize=14, fontname='helv')
    doc.save(str(caminho))
    doc.close()
    return caminho


def _rotulos(caminho) -> list:
    with fitz.open(str(caminho)) as doc:
        return [page.get_text().strip() for page in doc]


@pytest.fixture
def a(tmp_path):
    return _pdf(tmp_path / 'a.pdf', 'A', 3)


@pytest.fixture
def b(tmp_path):
    return _pdf(tmp_path / 'b.pdf', 'B', 4)


# ── selecao de paginas ───────────────────────────────────────────────────────

@pytest.mark.parametrize('texto,total,esperado', [
    ('', 5, [0, 1, 2, 3, 4]),
    ('   ', 3, [0, 1, 2]),
    ('3', 5, [2]),
    ('2-4', 5, [1, 2, 3]),
    ('3-', 5, [2, 3, 4]),
    ('-2', 5, [0, 1]),
    ('1-2, 5', 5, [0, 1, 4]),
    ('5;1', 5, [4, 0]),           # a ordem pedida e a ordem do resultado
    ('2, 2', 5, [1, 1]),          # repetir e permitido
    (' 1 - 2 ,  4 ', 5, [0, 1, 3]),
    ('1-3,', 5, [0, 1, 2]),       # virgula sobrando nao atrapalha
])
def test_selecao_valida(texto, total, esperado):
    assert paginas_da_selecao(texto, total) == esperado


@pytest.mark.parametrize('texto', ['abc', '1-x', '--3', '-', '0', '1-0', '5 5', '2-1', '1.5', ',', '1-2-3'])
def test_selecao_invalida_da_mensagem(texto):
    with pytest.raises(JuntarError):
        paginas_da_selecao(texto, 5)


def test_selecao_fora_do_total_diz_qual_pagina_e_quantas_tem():
    with pytest.raises(JuntarError, match=r'página 7 não existe \(o arquivo tem 5\)'):
        paginas_da_selecao('2, 7', 5)
    with pytest.raises(JuntarError, match='invertido'):
        paginas_da_selecao('4-2', 5)


# ── juntar ───────────────────────────────────────────────────────────────────

def test_junta_na_ordem_da_lista(a, b, tmp_path):
    destino = tmp_path / 'juntado.pdf'
    r = juntar_pdfs([EntradaJuntar(str(b)), EntradaJuntar(str(a))], str(destino))
    assert _rotulos(destino) == ['B-1', 'B-2', 'B-3', 'B-4', 'A-1', 'A-2', 'A-3']
    assert (r.arquivos, r.paginas) == (2, 7)


def test_usa_so_as_paginas_escolhidas_na_ordem_pedida(a, b, tmp_path):
    destino = tmp_path / 'juntado.pdf'
    r = juntar_pdfs([EntradaJuntar(str(a), '3, 1'), EntradaJuntar(str(b), '2-3')], str(destino))
    assert _rotulos(destino) == ['A-3', 'A-1', 'B-2', 'B-3']
    assert r.paginas == 4


def test_um_arquivo_com_selecao_extrai_paginas(b, tmp_path):
    destino = tmp_path / 'extraido.pdf'
    juntar_pdfs([EntradaJuntar(str(b), '2-')], str(destino))
    assert _rotulos(destino) == ['B-2', 'B-3', 'B-4']


def test_mesmo_arquivo_duas_vezes_e_pagina_repetida(a, tmp_path):
    destino = tmp_path / 'juntado.pdf'
    juntar_pdfs([EntradaJuntar(str(a), '1'), EntradaJuntar(str(a), '1-2'), EntradaJuntar(str(a), '2, 2')],
                str(destino))
    assert _rotulos(destino) == ['A-1', 'A-1', 'A-2', 'A-2', 'A-2']


def test_paginas_de_tamanhos_diferentes_mantem_o_tamanho(a, tmp_path):
    paisagem = _pdf(tmp_path / 'p.pdf', 'P', 1, largura=842, altura=595)
    destino = tmp_path / 'juntado.pdf'
    juntar_pdfs([EntradaJuntar(str(a), '1'), EntradaJuntar(str(paisagem))], str(destino))
    with fitz.open(str(destino)) as doc:
        assert [(round(p.rect.width), round(p.rect.height)) for p in doc] == [(595, 842), (842, 595)]


def test_origens_nao_sao_alteradas(a, b, tmp_path):
    antes = (a.read_bytes(), b.read_bytes())
    juntar_pdfs([EntradaJuntar(str(a)), EntradaJuntar(str(b))], str(tmp_path / 'j.pdf'))
    assert (a.read_bytes(), b.read_bytes()) == antes


def test_progresso_uma_vez_por_arquivo(a, b, tmp_path):
    chamadas = []
    juntar_pdfs([EntradaJuntar(str(a)), EntradaJuntar(str(b))], str(tmp_path / 'j.pdf'),
                lambda atual, total: chamadas.append((atual, total)))
    assert chamadas == [(1, 2), (2, 2)]


def test_cancelar_nao_grava_nada(a, b, tmp_path):
    destino = tmp_path / 'j.pdf'

    def cancela(atual, total):
        raise JuntarCancelado()

    with pytest.raises(JuntarCancelado):
        juntar_pdfs([EntradaJuntar(str(a)), EntradaJuntar(str(b))], str(destino), cancela)
    assert not destino.exists() and list(tmp_path.glob('*.parcial')) == []


def test_sobrescreve_destino_existente_sem_deixar_parcial(a, b, tmp_path):
    destino = tmp_path / 'j.pdf'
    destino.write_bytes(b'antigo')
    juntar_pdfs([EntradaJuntar(str(a))], str(destino))
    assert _rotulos(destino) == ['A-1', 'A-2', 'A-3'] and list(tmp_path.glob('*.parcial')) == []


# ── erros ────────────────────────────────────────────────────────────────────

def test_lista_vazia_e_saida_sem_extensao_pdf(a, tmp_path):
    with pytest.raises(JuntarError, match='pelo menos um'):
        juntar_pdfs([], str(tmp_path / 'j.pdf'))
    with pytest.raises(JuntarError, match=r'\.pdf'):
        juntar_pdfs([EntradaJuntar(str(a))], str(tmp_path / 'j.txt'))


def test_saida_igual_a_uma_entrada_e_recusada(a, b, tmp_path):
    antes = a.read_bytes()
    with pytest.raises(JuntarError, match='saída'):
        juntar_pdfs([EntradaJuntar(str(b)), EntradaJuntar(str(a))], str(a))
    assert a.read_bytes() == antes


def test_erro_de_pagina_cita_o_arquivo_e_nao_cria_saida(a, b, tmp_path):
    destino = tmp_path / 'j.pdf'
    with pytest.raises(JuntarError, match=r'b\.pdf: A página 9 não existe'):
        juntar_pdfs([EntradaJuntar(str(a)), EntradaJuntar(str(b), '9')], str(destino))
    assert not destino.exists() and list(tmp_path.glob('*.parcial')) == []


def test_arquivo_inexistente_ou_que_nao_e_pdf(tmp_path):
    texto = tmp_path / 'x.pdf'
    texto.write_bytes(b'isto nao e um pdf')
    for caminho in (tmp_path / 'nao_existe.pdf', texto, tmp_path / 'a.txt'):
        with pytest.raises(JuntarError):
            juntar_pdfs([EntradaJuntar(str(caminho))], str(tmp_path / 'j.pdf'))


def test_pdf_com_senha_e_recusado_com_o_nome(a, tmp_path):
    protegido = tmp_path / 'trancado.pdf'
    with fitz.open(str(a)) as doc:
        doc.save(str(protegido), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='x', owner_pw='y')
    with pytest.raises(JuntarError, match='trancado.pdf" está protegido por senha'):
        juntar_pdfs([EntradaJuntar(str(protegido))], str(tmp_path / 'j.pdf'))
    with pytest.raises(JuntarError, match='senha'):
        contar_paginas(str(protegido))


def test_contar_paginas(b):
    assert contar_paginas(str(b)) == 4
