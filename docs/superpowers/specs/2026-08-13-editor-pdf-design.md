# Editor de PDF (edição de texto existente) — Design

Data: 2026-08-13
Projeto: PDF VOZ (leitor-voz)

## Contexto

O app hoje extrai o texto do PDF para um `QTextEdit` (modo leitura, `gui.py`) e lê em voz alta. Não existe
nenhuma visão da página original renderizada, nem qualquer forma de edição do conteúdo do PDF.

Esta feature adiciona um **modo "Editar PDF"** que permite trocar, apagar, adicionar e formatar texto
diretamente sobre a página original — preservando o resto do documento intacto. Escopo definido para
**PDF nativo (texto digital selecionável)**; PDF escaneado/imagem está fora do escopo desta versão.

## Objetivo

Trocar/corrigir texto existente, apagar texto, adicionar texto novo em área livre e formatar (negrito,
itálico, tamanho, cor, família de fonte), sem depender de ferramentas de terceiros pagas ou limitadas.

Ordem de prioridade de implementação: **1) trocar texto → 2) apagar texto → 3) adicionar texto → 4) formatação**.

## Não-objetivos (fora de escopo nesta versão)

- Edição de PDF escaneado/imagem (exigiria OCR + reconstrução, fidelidade muito menor).
- Inserção de texto no meio de um parágrafo existente empurrando o conteúdo ao redor (reflow real).
  Texto novo só entra em área livre da página.
- Reordenar/mesclar/dividir páginas, formulários, assinatura digital (podem virar features futuras
  separadas, não fazem parte deste design).
- Verificação automática de sobreposição ao adicionar texto em área "livre" — a responsabilidade de
  escolher um lugar vazio é do usuário nesta versão.

## Arquitetura

### Onde vive no app

Novo modo "Editar PDF", acessível por botão/aba ao lado do modo leitura em `gui.py`. Ao entrar nesse modo
com um PDF nativo aberto, a página é renderizada como imagem (`page.get_pixmap()` via PyMuPDF, já
dependência do projeto) num canvas rolável, página a página.

### Modelo de edição: spans

PyMuPDF extrai os "spans" de texto de cada página (`page.get_text("dict")`) — cada span é um trecho
contíguo com fonte/tamanho/cor/posição consistentes (tipicamente uma linha ou parte dela). Span é a
unidade de edição:

1. Usuário clica num span no canvas → vira caixa editável sobreposta na posição/tamanho exatos, com o
   texto atual pronto pra editar.
2. Uma barra de formatação (negrito, itálico, tamanho, cor, família de fonte) aparece junto à caixa.
3. Ao confirmar (Enter / clicar fora): a área antiga é redigida de verdade (`add_redact_annot` +
   `apply_redactions`) e o texto novo é escrito na mesma posição (`insert_text`), com a formatação
   escolhida.

Apagar um span = confirmar com o campo vazio (redige e não reinsere nada).

### Adicionar texto novo

Botão "Adicionar texto" ativa um modo de clique: usuário clica numa área livre da página → surge uma
caixa nova com a mesma barra de formatação → ao confirmar, o texto é inserido nessa posição exata
(`page.insert_text`) sem alterar mais nada na página. Sem verificação automática de sobreposição.

### Casamento de fonte

Ao reinserir texto (edição ou span reformatado), o app tenta reusar a fonte embutida original do PDF
(PyMuPDF consegue extrair fontes embutidas na maioria dos PDFs nativos). Se não for possível (fonte não
extraível, ou usuário escolheu família diferente da original), cai para uma fonte padrão aproximada
(mantendo serifada/sem-serifa e negrito/itálico). A interface mostra um aviso discreto ("fonte
aproximada") quando o fallback for usado, para o usuário saber quando conferir visualmente.

### Salvar

Sempre gera uma **cópia nova** do arquivo (ex: `documento_editado.pdf`) — nunca sobrescreve o PDF
original. Edições ficam em memória (documento aberto) até o clique em "Salvar".

### Desfazer

Dentro da sessão de edição, cada confirmação de span (edição, apagar ou inserção) vira um passo de
histórico — `Ctrl+Z` / botão "Desfazer" reverte o último passo, em memória. Não precisa persistir após
salvar: reverter depois disso é reabrir o PDF original (nunca tocado).

### Tratamento de erro

- **Falha ao aplicar redação/inserção numa página** (PDF corrompido, página com proteção): aborta só
  aquela operação, mensagem clara ao usuário, resto do documento permanece intacto.
- **PDF protegido por senha ou sem permissão de edição**: detectado ao entrar no modo Editar, avisa antes
  de permitir qualquer tentativa de edição.
- **Falha ao salvar** (disco cheio, arquivo em uso): mensagem de erro explícita; documento editado
  permanece em memória para nova tentativa de salvar.

## Testes

Automatizados (seguindo o padrão já usado no projeto):
- Extração de spans com posição/fonte/tamanho/cor corretos.
- Redação + reinserção preservando o restante da página.
- Fallback de fonte quando a original não é extraível.
- Inserção de texto novo em área livre.
- Geração da cópia nova sem alterar o arquivo original (hash/bytes do original inalterados).

Manual: abrir um PDF real, editar um trecho, apagar outro, adicionar um novo, formatar, salvar, e
comparar visualmente a cópia gerada com o original para confirmar que só o pretendido mudou.
