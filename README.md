# PDF VOZ

Aplicativo Windows que **lê PDF e Word em voz alta** com vozes neurais em português do Brasil, e
**edita o texto de PDFs** — trocar, apagar, inserir e formatar, salvando sempre em uma cópia nova.

Feito por Anderson Rodrigo Costa. Distribuição gratuita.

---

## Instalar (usuário)

Baixe o instalador na aba [**Releases**](https://github.com/danda265/pdf-voz/releases) e execute.

A instalação é **por usuário**, em `%LOCALAPPDATA%\Programs\PDF VOZ` — não pede senha de administrador
e cria um desinstalador em "Aplicativos e recursos".

### O aviso do Windows ao abrir o instalador

O executável não tem assinatura digital paga, então o Windows mostra uma tela azul dizendo
*"O Windows protegeu o seu PC"*. Isso não indica vírus — é o SmartScreen alertando que não conhece o
publicador. Para instalar:

1. Clique em **Mais informações**
2. Clique em **Executar assim mesmo**

## Usar

As ferramentas do topo — **Editar PDF**, **Converter**, **Juntar PDFs** e **Exportar MP3** — já estão
disponíveis ao abrir o app. Sem arquivo aberto, cada uma pede o arquivo na hora; só **Fechar arquivo**
espera haver um aberto.

### Ler em voz alta
Abra um PDF ou Word, escolha a voz e clique em **Ler**. Dá para ajustar velocidade e volume durante a
leitura, começar de uma página específica e exportar a narração em MP3.

### Editar um PDF
Com um PDF aberto, clique em **Editar PDF**. O documento aparece como imagem e **rola contínuo**,
como em qualquer leitor de PDF.

Quatro gestos, sem precisar ligar modo nenhum:

| | **Clique** | **Arrastar** |
|---|---|---|
| **Em cima do texto** | edita o trecho | move o trecho |
| **Em área em branco** | adiciona texto ali | seleciona vários trechos |


- **Clique em um trecho de texto** para abrir a caixa de edição — troque o texto, ou apague tudo para
  remover o trecho. A barra tem negrito, itálico, tamanho, cor e a lista de fontes.
- **Enter** quebra a linha dentro da caixa; **Ctrl+Enter** confirma. O texto também quebra sozinho
  quando chega na margem.
- **Alinhar**: manter onde está, à esquerda, centralizado, à direita ou justificado. E **entrelinha**
  simples, 1,5 ou dupla.
- **Mover**: arraste o trecho, ou use as setas da caixa para ajuste fino — a posição nova aparece
  desenhada na página antes de você confirmar.
- **Vários trechos de uma vez**: arraste um retângulo por cima das linhas. Cada uma mantém a própria
  formatação; só o que você alterar na caixa vale para todas.
- **Ctrl+Z** ou **Desfazer** volta a última alteração.
- **Salvar cópia** grava `nome_editado.pdf` ao lado do original.

**O arquivo original nunca é alterado.** Toda edição vai para uma cópia nova.

### Juntar PDFs
**Juntar PDFs** abre uma janela para montar um PDF novo a partir de vários:

- **Adicionar PDFs...** (ou arraste os arquivos para a janela). Se há um PDF aberto no app, ele já
  entra na lista.
- **▲ Subir / ▼ Descer** mudam a ordem: o resultado segue a ordem da lista.
- Na coluna **Quais páginas usar** escreva as páginas que quer de cada arquivo — `3`, `2-5`, `8-`
  (da 8 até o fim), `-3` (até a 3) ou combinações como `1-3, 5, 8-`. Em branco, o arquivo entra
  inteiro. As páginas saem na ordem em que você as escreve (`5, 1` coloca a 5 antes da 1) e dá para
  repetir uma página. Com um arquivo só, vira "extrair páginas".
- O resumo mostra quantas páginas o resultado terá e avisa qual arquivo está com a seleção errada.

Os arquivos originais nunca são alterados e o resultado só aparece no disco quando termina. PDFs com
senha precisam ser abertos e salvos sem senha antes. Os marcadores (índice) de cada arquivo não são
levados para o PDF juntado.

### Converter para PowerPoint
Com um PDF aberto, **Converter** → escolha o modo e o local onde salvar o `.pptx`:

- **PowerPoint editável** — cada página vira um slide remontado com objetos do PowerPoint, na
  mesma ordem de empilhamento do PDF:
  - **texto** em caixas de texto, na mesma posição, fonte, tamanho e cor;
  - **formas** (retângulos, retângulos arredondados, elipses, linhas, polígonos e curvas) com o
    preenchimento, o contorno, o tracejado e a transparência do PDF: dá para mover, recolorir,
    redimensionar, editar os pontos ou apagar;
  - **fotos e imagens** soltas, com a transparência, para trocar, recortar ou apagar;
  - o retângulo que cobre a página inteira vira o **fundo do slide**.
- **PowerPoint só com imagens** — cada página vira uma imagem no slide: idêntico ao PDF, mas
  sem nada para editar.

**Nada fica diferente do PDF sem aviso.** Antes de usar, o app redesenha a página só com os objetos
que vai criar e compara com a original; se uma foto cortada em canto redondo, uma transparência em
grupo ou qualquer outra coisa mudaria a aparência, aquela parte (ou a página) continua como imagem.
Ficam como imagem no slide: degradês e sombreados, formas dentro de recortes de formato especial,
páginas com centenas de traços (texto vetorizado, mapas), PDF escaneado, página girada e texto na
vertical. Ao terminar, o app diz quantas formas, imagens e caixas de texto foram criadas e em quantas
páginas algo ficou como imagem.

Limites: as quebras de linha são as do PDF (cada linha é fixa, o PowerPoint não reflui o parágrafo),
o espaçamento entre letras não é reproduzido, e, se a fonte original não existir no computador, o
PowerPoint usa uma parecida. As sombras que o PowerPoint gera ao exportar para PDF chegam como
imagens soltas ao lado de cada forma. O PowerPoint não tem como "inserir design novo" automático
(sugestões de layout) a partir de um PDF: o que se recupera são os objetos do slide, não o tema.

### Abrir PDFs direto no app
Clique com o botão direito em um PDF → **Abrir com** → **Escolher outro aplicativo** → **PDF VOZ** →
marque *"Sempre usar este aplicativo"*.

## Aviso de versão nova

Ao abrir, o app consulta a página pública de *releases* deste repositório para saber se
existe versão mais recente. Se existir, aparece um aviso discreto no rodapé com o link.
Nada é baixado ou instalado automaticamente, nenhum dado seu é enviado, e sem internet o
aviso simplesmente não aparece.

## Limitações conhecidas

- A edição funciona em **PDF nativo** (texto digital selecionável). PDF escaneado é imagem — dá para
  ler com OCR, mas não para editar o texto.
- O texto quebra sozinho na margem. Se um trecho passar a ocupar mais linhas, os trechos
  **selecionados junto com ele** descem para abrir espaço — mas o conteúdo **fora da seleção** não
  desce, e pode acabar coberto. O app avisa quando isso pode acontecer; a saída é incluir também as
  linhas de baixo na seleção. PDF não tem parágrafo fluido como o Word.
- Texto novo entra apenas em área livre da página — não empurra o conteúdo existente.
- Se a fonte original do PDF não puder ser reutilizada, o app usa a mais parecida instalada no sistema
  e avisa *"fonte aproximada"*.
- A voz neural é um serviço online: precisa de internet e leva alguns segundos até o primeiro som.

## Vozes disponíveis

Francisca, Antônio, Brenda, Donato e Elza — todas neurais, em português do Brasil.

---

## Desenvolvimento

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest, para rodar os testes
python main.py
```

Testes:

```powershell
python -m pytest tests -v
```

Gerar o instalador (precisa do [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
python -m PyInstaller --noconfirm --clean leitor.spec
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

Feche todas as instâncias do app antes de compilar. A versão é definida em `APP_VERSION` (`gui.py`) e
deve bater com `MyAppVersion` em `installer.iss`.

### Organização

| Arquivo | Responsabilidade |
|---|---|
| `gui.py` | Janela principal, modo leitura e modo edição |
| `pdf_editor.py` | Motor de edição de PDF (sem dependência de interface) |
| `pdf_editor_view.py` | Canvas da página e caixa de edição |
| `pdf_to_pptx.py` · `pdf_to_pptx_objetos.py` | Conversão de PDF para PowerPoint (sem dependência de interface): montagem do slide e recriação das formas e imagens |
| `pdf_merge.py` · `pdf_merge_dialog.py` | Juntar PDFs: motor (sem interface) e janela de montagem |
| `document_reader.py` · `pdf_reader.py` · `word_reader.py` | Extração de texto |
| `tts_engine.py` · `audio_player.py` | Síntese e reprodução de voz |
| `ocr.py` | OCR para PDFs escaneados |

---

## Licença

Este programa é software livre, sob a **GNU Affero General Public License v3.0** — veja
[LICENSE](LICENSE).

A AGPL é obrigatória aqui, não uma escolha: o app usa **PyMuPDF** (AGPL-3.0) e **PyQt6** (GPL-3.0), e
qualquer trabalho que se combine com essas bibliotecas precisa ser distribuído sob os mesmos termos,
com o código-fonte disponível — o que este repositório cumpre.

### Componentes de terceiros

| Componente | Licença |
|---|---|
| PyMuPDF | AGPL-3.0 ou licença comercial Artifex |
| PyQt6 | GPL-3.0 |
| pygame-ce | LGPL-2.1 |
| python-docx | MIT |
| python-pptx | MIT |
| Pillow | MIT-CMU |
| pytesseract | Apache-2.0 |
| Tesseract OCR | Apache-2.0 |

As vozes vêm do serviço de leitura em voz alta da Microsoft, acessado pela biblioteca `edge-tts`. É um
cliente não oficial: pode parar de funcionar sem aviso, e não é adequado para uso comercial.
