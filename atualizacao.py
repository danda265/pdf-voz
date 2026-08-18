"""Aviso de versão nova.

Consulta a API pública do GitHub Releases e compara com a versão instalada. Não baixa
nem instala nada: só avisa e oferece o link. Sem servidor próprio e sem dependência
nova — `urllib` é da biblioteca padrão.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Optional, Tuple

API_RELEASES = 'https://api.github.com/repos/danda265/pdf-voz/releases/latest'
TEMPO_LIMITE = 6   # segundos; o app não pode ficar esperando a rede para abrir


def _numeros(versao: str) -> Tuple[int, ...]:
    """'v1.10.2' -> (1, 10, 2). Partes não numéricas viram 0."""
    limpa = re.sub(r'^[vV]', '', (versao or '').strip())
    partes = re.split(r'[.\-+]', limpa)
    numeros = []
    for parte in partes:
        digitos = re.match(r'\d+', parte)
        if not digitos:
            break
        numeros.append(int(digitos.group()))
    return tuple(numeros) or (0,)


def e_mais_nova(disponivel: str, instalada: str) -> bool:
    """Compara número a número — '1.10.0' é mais nova que '1.9.0', que a comparação de
    texto erraria."""
    a, b = _numeros(disponivel), _numeros(instalada)
    tamanho = max(len(a), len(b))
    a += (0,) * (tamanho - len(a))
    b += (0,) * (tamanho - len(b))
    return a > b


def ler_resposta(dados: dict) -> Optional[Tuple[str, str]]:
    """(versão, link) a partir do JSON do GitHub, ou None se vier incompleto/rascunho."""
    if not isinstance(dados, dict) or dados.get('draft'):
        return None
    versao = dados.get('tag_name')
    link = dados.get('html_url')
    if not versao or not link:
        return None
    return str(versao), str(link)


def procurar_novidade(versao_instalada: str, url: str = API_RELEASES) -> Optional[Tuple[str, str]]:
    """(versão, link) se houver versão mais nova publicada; None em qualquer outro caso.

    Nunca levanta exceção: sem internet, com a API fora do ar ou com resposta estranha, o
    app simplesmente não avisa nada. Uma falha aqui não pode atrapalhar quem só quer ler
    um documento."""
    try:
        requisicao = urllib.request.Request(
            url, headers={'Accept': 'application/vnd.github+json',
                          'User-Agent': 'PDF-VOZ'}
        )
        with urllib.request.urlopen(requisicao, timeout=TEMPO_LIMITE) as resposta:
            dados = json.loads(resposta.read().decode('utf-8'))
    except Exception:
        return None
    lida = ler_resposta(dados)
    if not lida:
        return None
    versao, link = lida
    return (versao, link) if e_mais_nova(versao, versao_instalada) else None
