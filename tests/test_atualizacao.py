from __future__ import annotations

from atualizacao import e_mais_nova, ler_resposta, procurar_novidade


def test_compara_versao_por_numero_nao_por_texto():
    """'1.10.0' é mais nova que '1.9.0' — comparação de texto erraria isso."""
    assert e_mais_nova('1.10.0', '1.9.0') is True
    assert e_mais_nova('v1.3.0', '1.2.0') is True
    assert e_mais_nova('1.2.0', '1.2.0') is False
    assert e_mais_nova('1.2.0', '1.3.0') is False
    assert e_mais_nova('2.0', '1.9.9') is True


def test_versoes_de_tamanhos_diferentes():
    assert e_mais_nova('1.2.1', '1.2') is True
    assert e_mais_nova('1.2', '1.2.0') is False


def test_le_a_resposta_do_github():
    dados = {'tag_name': 'v1.3.0', 'html_url': 'https://exemplo/releases/v1.3.0'}
    assert ler_resposta(dados) == ('v1.3.0', 'https://exemplo/releases/v1.3.0')


def test_ignora_rascunho_e_resposta_incompleta():
    assert ler_resposta({'tag_name': 'v9', 'html_url': 'x', 'draft': True}) is None
    assert ler_resposta({'tag_name': 'v9'}) is None
    assert ler_resposta({}) is None
    assert ler_resposta('não é dicionário') is None


def test_sem_internet_nao_levanta_nem_avisa():
    """Uma falha de rede não pode atrapalhar quem só quer abrir um documento."""
    assert procurar_novidade('1.2.0', url='http://127.0.0.1:9/nao-existe') is None


def test_nao_avisa_quando_ja_esta_na_versao_publicada(monkeypatch, tmp_path):
    import json
    import atualizacao

    class RespostaFalsa:
        def read(self):
            return json.dumps({'tag_name': 'v1.2.0', 'html_url': 'https://x'}).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(atualizacao.urllib.request, 'urlopen', lambda *a, **k: RespostaFalsa())
    assert atualizacao.procurar_novidade('1.2.0') is None
    assert atualizacao.procurar_novidade('1.1.0') == ('v1.2.0', 'https://x')
