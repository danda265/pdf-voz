# Memoria do Projeto - Leitor PDF e Word Voz Natural

Data: 22/06/2026

## Objetivo do Projeto

Criar um aplicativo completo para Windows em Python que leia documentos em voz alta com voz natural em portugues do Brasil.

O pedido inicial era um leitor de PDF chamado "PDF Voz Natural", mas depois foi ajustado para:

- Nao criar pasta `lab` ou `laboratorio_ctrl`.
- Criar um projeto separado com nome ligado a leitor de PDF.
- Permitir leitura de PDF e tambem Word.

Nome atual do projeto:

`leitor_pdf_word_voz_natural`

Pasta do projeto:

`C:\Users\trlpa\OneDrive\Documentos\leitor_pdf_word_voz_natural`

## Funcionalidades Pedidas

- Abrir arquivos PDF.
- Abrir arquivos Word.
- Extrair texto mantendo a ordem do documento.
- Exibir o texto extraido na tela.
- Ler o texto em voz alta com voz neural natural em portugues do Brasil.
- Respeitar acentuacao, pontuacao, pausas, numeros, abreviacoes, paragrafos e caracteres especiais.
- Usar interface grafica moderna.
- Ter botoes:
  - Abrir PDF/Word
  - Fechar arquivo
  - Ler
  - Pausar
  - Continuar
  - Parar
  - Exportar MP3
- Ter configuracoes:
  - Selecao de voz
  - Velocidade
  - Volume
  - OCR opcional
- Mostrar progresso da leitura.
- Mostrar pagina atual e total de paginas.
- Dividir textos grandes em blocos para evitar limite do TTS.
- Evitar travamentos da interface usando threads.
- Exportar a narracao completa em MP3.
- Preparar para gerar executavel no Windows.

## Tecnologias Usadas

- Python
- PyQt6 para interface grafica
- PyMuPDF / fitz para leitura de PDF
- edge-tts para sintese de voz neural
- pygame / pygame-ce para reproducao de audio
- python-docx para arquivos `.docx`
- pywin32 para converter `.doc` antigo quando o Microsoft Word estiver disponivel
- pytesseract e Pillow para OCR opcional
- PyInstaller para gerar executavel

## Vozes Configuradas

Voz padrao:

- `pt-BR-FranciscaNeural`

Vozes disponiveis:

- `pt-BR-FranciscaNeural`
- `pt-BR-AntonioNeural`
- `pt-BR-BrendaNeural`
- `pt-BR-DonatoNeural`
- `pt-BR-ElzaNeural`

## Estrutura Criada

Arquivos principais:

- `main.py`
- `gui.py`
- `document_reader.py`
- `pdf_reader.py`
- `word_reader.py`
- `tts_engine.py`
- `audio_player.py`
- `ocr.py`
- `utils.py`
- `requirements.txt`
- `README.md`
- `build_exe.ps1`
- `MEMORIA_DO_PROJETO.md`

Pastas:

- `assets`
- `temp`
- `build`
- `dist`

## O Que Cada Arquivo Faz

`main.py`

- Ponto de entrada do aplicativo.
- Chama a interface grafica.

`gui.py`

- Cria a janela principal em PyQt6.
- Controla botoes, barra de progresso, editor de texto, selecao de voz, velocidade e volume.
- Usa QThread para carregar documentos, ler em voz alta e exportar MP3 sem travar a tela.

`document_reader.py`

- Decide se o arquivo e PDF ou Word.
- Encaminha para o leitor correto.

`pdf_reader.py`

- Le PDF com PyMuPDF.
- Extrai texto pagina por pagina.
- Se a pagina nao tiver texto, tenta OCR quando ativado.

`word_reader.py`

- Le `.docx` com python-docx.
- Para `.doc`, tenta converter com Microsoft Word via pywin32.

`tts_engine.py`

- Usa edge-tts.
- Divide texto grande em blocos.
- Gera audio por bloco.
- Exporta a narracao completa para MP3.

`audio_player.py`

- Usa pygame para tocar audio.
- Implementa pausar, continuar e parar.

`ocr.py`

- Converte pagina de PDF em imagem e executa OCR com pytesseract.

`utils.py`

- Tem a funcao `clean_text(text)`.
- Remove espacos duplicados.
- Corrige quebras excessivas.
- Preserva pontuacao e acentos.
- Divide texto em blocos seguros.

`requirements.txt`

- Lista dependencias do projeto.
- Foi ajustado para usar `pygame-ce` no Python 3.14, porque o `pygame` tradicional falhou ao instalar nessa versao.

`build_exe.ps1`

- Script para gerar o executavel.
- Foi ajustado para usar Python 3.11 explicitamente ao empacotar com PyInstaller.

## Problemas Encontrados e Corrigidos

### 1. Pasta errada

O workspace inicial apontava para:

`C:\Users\trlpa\OneDrive\Documentos\laboratorio_ctrl`

Mas o usuario pediu para nao criar pasta `lab` ou `laboratorio_ctrl`.

Solucao:

- O projeto foi criado em:

`C:\Users\trlpa\OneDrive\Documentos\leitor_pdf_word_voz_natural`

### 2. Falha ao instalar pygame no Python 3.14

Erro:

- `pygame` tentou compilar do zero.
- Faltou suporte de compilacao/distutils para essa combinacao.

Solucao:

- Alterado `requirements.txt`:

```txt
pygame>=2.5; python_version < "3.14"
pygame-ce>=2.5; python_version >= "3.14"
```

### 3. Executavel antigo abriu com erro de PyQt6

Erro visto na tela:

```txt
ModuleNotFoundError: No module named 'PyQt6'
```

Causa:

- O PyInstaller usou Python 3.11, mas o PyQt6 estava instalado no Python 3.14.

Solucao:

- Instaladas as dependencias tambem no Python 3.11:

```powershell
py -3.11 -m pip install -r requirements.txt
```

- Gerado um novo executavel corrigido.

## Executaveis Gerados

Executavel antigo com erro:

`C:\Users\trlpa\OneDrive\Documentos\leitor_pdf_word_voz_natural\dist\Leitor PDF e Word - Voz Natural.exe`

Executavel corrigido:

`C:\Users\trlpa\OneDrive\Documentos\leitor_pdf_word_voz_natural\dist\Leitor PDF e Word - Voz Natural Corrigido.exe`

Este e o arquivo que deve ser usado agora.

## Comandos Importantes

Entrar na pasta:

```powershell
cd "C:\Users\trlpa\OneDrive\Documentos\leitor_pdf_word_voz_natural"
```

Instalar dependencias no Python padrao:

```powershell
python -m pip install -r requirements.txt
```

Instalar dependencias no Python 3.11:

```powershell
py -3.11 -m pip install -r requirements.txt
```

Rodar pelo codigo-fonte:

```powershell
python main.py
```

Gerar executavel:

```powershell
.\build_exe.ps1
```

Ou manualmente:

```powershell
py -3.11 -m PyInstaller --clean --onefile --windowed --name "Leitor PDF e Word - Voz Natural Corrigido" main.py
```

## Estado Atual

- Codigo-fonte criado.
- Dependencias instaladas no Python 3.14 e no Python 3.11.
- Sintaxe dos arquivos validada.
- Executavel corrigido gerado.
- O proximo passo e testar o arquivo:

`dist\Leitor PDF e Word - Voz Natural Corrigido.exe`

## Observacoes

- Para OCR funcionar em PDFs escaneados, alem dos pacotes Python, o Tesseract OCR precisa estar instalado no Windows.
- Para abrir `.doc` antigo, o Microsoft Word precisa estar instalado e o `pywin32` precisa estar disponivel.
- `.docx` funciona diretamente com `python-docx`.
- A leitura por voz usa internet, porque o `edge-tts` se conecta ao servico de voz neural da Microsoft.
