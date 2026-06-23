# Leitor PDF e Word - Voz Natural

Aplicativo Windows em Python para abrir PDF, DOCX e DOC, extrair texto e ler em voz alta com vozes neurais em portugues do Brasil usando Edge TTS.
No Python 3.14, o projeto usa `pygame-ce`, que fornece o mesmo import `pygame` usado pelo programa.

## Instalar

```powershell
pip install -r requirements.txt
```

Para OCR em PDFs escaneados, instale tambem o Tesseract OCR para Windows e deixe o executavel no PATH. O idioma recomendado e `por`.

## Executar

```powershell
python main.py
```

## Gerar executavel

```powershell
pyinstaller --onefile --windowed main.py
```

Ou use:

```powershell
.\build_exe.ps1
```

O executavel ficara em `dist/Leitor PDF e Word - Voz Natural.exe`.

## Vozes incluidas

- pt-BR-FranciscaNeural
- pt-BR-AntonioNeural
- pt-BR-BrendaNeural
- pt-BR-DonatoNeural
- pt-BR-ElzaNeural

## Observacoes

- DOCX e lido diretamente com `python-docx`.
- DOC antigo e convertido via Microsoft Word quando `pywin32` e Word estiverem instalados.
- Pausar e continuar preservam a posicao do audio atual.
- Textos grandes sao divididos em blocos para evitar limites do Edge TTS.
