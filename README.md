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

### Ler em voz alta
Abra um PDF ou Word, escolha a voz e clique em **Ler**. Dá para ajustar velocidade e volume durante a
leitura, começar de uma página específica e exportar a narração em MP3.

### Editar um PDF
Com um PDF aberto, clique em **Editar PDF**. A página aparece como imagem:

- **Clique em um trecho de texto** para abrir a caixa de edição — troque o texto, ou apague tudo para
  remover o trecho. A barra tem negrito, itálico, tamanho, cor e a lista de fontes.
- **Enter** quebra a linha dentro da caixa; **Ctrl+Enter** confirma. O texto também quebra sozinho
  quando chega na margem.
- **Alinhar**: manter onde está, à esquerda, centralizado, à direita ou justificado. E **entrelinha**
  simples, 1,5 ou dupla.
- **Mover**: arraste o trecho na página, ou use as setas da caixa para ajuste fino.
- **Adicionar texto** insere texto novo em um espaço em branco da página.
- **Ctrl+Z** ou **Desfazer** volta a última alteração.
- **Salvar cópia** grava `nome_editado.pdf` ao lado do original.

**O arquivo original nunca é alterado.** Toda edição vai para uma cópia nova.

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
- O texto quebra sozinho na margem, mas as linhas extras **descem sobre o que está abaixo** — o app
  avisa quando o trecho passa a ocupar mais de uma linha. O conteúdo existente não é empurrado para
  baixo: PDF não tem parágrafo fluido como o Word.
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
| Pillow | MIT-CMU |
| pytesseract | Apache-2.0 |
| Tesseract OCR | Apache-2.0 |

As vozes vêm do serviço de leitura em voz alta da Microsoft, acessado pela biblioteca `edge-tts`. É um
cliente não oficial: pode parar de funcionar sem aviso, e não é adequado para uso comercial.
