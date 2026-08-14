# Editor de PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar ao PDF VOZ um modo "Editar PDF" que troca, apaga, adiciona e formata texto diretamente
sobre a página original de um PDF nativo, sempre salvando uma cópia nova (nunca sobrescrevendo o original).

**Architecture:** Um motor puro Python (`pdf_editor.py`, sem Qt) faz extração de spans de texto via
PyMuPDF, resolução/fallback de fonte, redação+reinserção (trocar/apagar), inserção em área livre, sessão
de edição com undo, e salvamento seguro em cópia nova. Uma camada de visualização (`pdf_editor_view.py`)
renderiza a página como pixmap num `QLabel`/`QScrollArea`, faz hit-test de cliques contra os spans, e
expõe um popup de edição com barra de formatação. `gui.py` ganha um `QStackedWidget` que alterna entre o
modo leitura existente e o novo modo edição.

**Tech Stack:** Python 3.11/3.14, PyMuPDF (`fitz`, já dependência), PyQt6 (já dependência), pytest +
pytest-qt (novas dependências, só de desenvolvimento).

## Global Constraints

- Escopo desta versão: apenas **PDF nativo** (texto digital selecionável). PDF escaneado/imagem fica fora.
- **Nunca sobrescrever o arquivo original.** Salvar sempre gera uma cópia nova (`<nome>_editado.pdf`,
  incrementando sufixo em caso de colisão).
- Texto novo só entra em **área livre** da página — sem reflow, sem empurrar conteúdo existente. Sem
  verificação automática de sobreposição (responsabilidade do usuário).
- Reusa `PyMuPDF>=1.24` e `PyQt6>=6.7`, já fixados em `requirements.txt` — nenhuma dependência nova de
  runtime/build. `pytest`/`pytest-qt` são **só de desenvolvimento** (`requirements-dev.txt`), não entram
  no `.spec` do PyInstaller nem no instalador.
- Todos os comandos de teste assumem execução a partir da raiz do projeto:
  `C:\Users\trlpa\OneDrive\Desktop\Projetos\leitor-voz`.
- Espec de referência: `docs/superpowers/specs/2026-08-13-editor-pdf-design.md`.

---

## File Structure

- **Create** `pdf_editor.py` — motor de edição puro (sem Qt): extração de spans, resolução de fonte,
  redação+reinserção, inserção livre, sessão com undo, abertura segura e salvamento em cópia.
- **Create** `pdf_editor_view.py` — widgets Qt: canvas que renderiza a página e faz hit-test, popup de
  edição com barra de formatação.
- **Modify** `gui.py` — novo botão/modo "Editar PDF", `QStackedWidget` alternando leitura/edição, glue
  entre os widgets de `pdf_editor_view.py` e o motor de `pdf_editor.py`.
- **Create** `tests/conftest.py` — fixture `sample_pdf` (PDF mínimo gerado em memória para os testes).
- **Create** `tests/test_pdf_editor.py` — testes do motor (Tasks 1–6).
- **Create** `tests/test_gui_edit_mode.py` — teste headless do modo edição (Task 9).
- **Create** `requirements-dev.txt` — `pytest`, `pytest-qt`.

---

### Task 1: Extração de spans de texto

**Files:**
- Create: `pdf_editor.py`
- Create: `tests/conftest.py`
- Create: `requirements-dev.txt`
- Test: `tests/test_pdf_editor.py`

**Interfaces:**
- Produces: `TextSpan` (dataclass: `text: str`, `bbox: Tuple[float,float,float,float]`,
  `origin: Tuple[float,float]`, `font_name: str`, `size: float`, `color: Tuple[float,float,float]`,
  `bold: bool`, `italic: bool`, `serifed: bool`); `spans_for_page(page: fitz.Page) -> List[TextSpan]`.

- [ ] **Step 1: Criar `requirements-dev.txt`**

```
pytest>=8.0
pytest-qt>=4.4
```

- [ ] **Step 2: Instalar dependências de teste**

Run: `py -3.14 -m pip install -r requirements-dev.txt`
Expected: instalação concluída sem erro.

- [ ] **Step 3: Criar `tests/conftest.py` com a fixture de PDF de teste**

```python
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
```

- [ ] **Step 4: Escrever o teste que falha**

Create `tests/test_pdf_editor.py`:

```python
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
```

- [ ] **Step 5: Rodar o teste e confirmar que falha**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py::test_spans_for_page_extracts_text_and_position -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pdf_editor'`

- [ ] **Step 6: Implementar `pdf_editor.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import fitz

Color = Tuple[float, float, float]


@dataclass
class TextSpan:
    text: str
    bbox: Tuple[float, float, float, float]
    origin: Tuple[float, float]
    font_name: str
    size: float
    color: Color
    bold: bool
    italic: bool
    serifed: bool


def _int_to_rgb(value: int) -> Color:
    r = ((value >> 16) & 255) / 255
    g = ((value >> 8) & 255) / 255
    b = (value & 255) / 255
    return (r, g, b)


def spans_for_page(page: fitz.Page) -> List[TextSpan]:
    spans: List[TextSpan] = []
    raw = page.get_text('dict')
    for block in raw.get('blocks', []):
        for line in block.get('lines', []):
            for s in line.get('spans', []):
                flags = s.get('flags', 0)
                spans.append(TextSpan(
                    text=s['text'],
                    bbox=tuple(s['bbox']),
                    origin=tuple(s['origin']),
                    font_name=s['font'],
                    size=float(s['size']),
                    color=_int_to_rgb(s['color']),
                    bold=bool(flags & (1 << 4)),
                    italic=bool(flags & (1 << 1)),
                    serifed=bool(flags & (1 << 2)),
                ))
    return spans
```

- [ ] **Step 7: Rodar o teste e confirmar que passa**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py::test_spans_for_page_extracts_text_and_position -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add pdf_editor.py tests/conftest.py tests/test_pdf_editor.py requirements-dev.txt
git commit -m "feat: extrai spans de texto de uma pagina de PDF (motor do editor)"
```

---

### Task 2: Resolução e fallback de fonte

**Files:**
- Modify: `pdf_editor.py`
- Test: `tests/test_pdf_editor.py`

**Interfaces:**
- Consumes: `TextSpan` (Task 1).
- Produces: `FormatOverride` (dataclass: `bold: Optional[bool] = None`, `italic: Optional[bool] = None`,
  `size: Optional[float] = None`, `color: Optional[Color] = None`, `family: Optional[str] = None`);
  `FontChoice` (dataclass: `fontname: str`, `fontbuffer: Optional[bytes]`, `size: float`, `color: Color`,
  `used_fallback: bool`); `resolve_font(doc: fitz.Document, page: fitz.Page, span: Optional[TextSpan], override: Optional[FormatOverride]) -> FontChoice`.

- [ ] **Step 1: Escrever os testes que falham**

Add to `tests/test_pdf_editor.py`:

```python
import os

import pytest

from pdf_editor import FormatOverride, resolve_font

ARIAL_PATH = r'C:\Windows\Fonts\arial.ttf'


@pytest.fixture
def embedded_font_pdf(tmp_path):
    if not os.path.exists(ARIAL_PATH):
        pytest.skip('Arial nao encontrada em C:\\Windows\\Fonts')
    path = tmp_path / 'embedded.pdf'
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_font(fontname='ArialCustom', fontfile=ARIAL_PATH)
    page.insert_text((72, 100), 'Texto com fonte embutida', fontsize=14, fontname='ArialCustom', color=(0, 0, 0))
    doc.save(str(path))
    doc.close()
    return path


def test_resolve_font_reuses_embedded_font_when_available(embedded_font_pdf):
    doc = fitz.open(str(embedded_font_pdf))
    page = doc[0]
    span = spans_for_page(page)[0]
    choice = resolve_font(doc, page, span, override=None)
    doc.close()
    assert choice.used_fallback is False
    assert choice.fontbuffer


def test_resolve_font_falls_back_when_family_not_embedded(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = spans_for_page(page)[0]
    override = FormatOverride(family='Comic Sans MS')
    choice = resolve_font(doc, page, span, override)
    doc.close()
    assert choice.used_fallback is True
    assert choice.fontname in ('helv', 'heit', 'hebo', 'hebi', 'tiro', 'tibo', 'tiit', 'tibi')
```

(`spans_for_page` já está importado no topo do arquivo pela Task 1 — adicione `resolve_font, FormatOverride`
ao import existente de `pdf_editor`.)

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -k resolve_font -v`
Expected: FAIL com `ImportError: cannot import name 'resolve_font'`

- [ ] **Step 3: Implementar a resolução de fonte em `pdf_editor.py`**

Add:

```python
import re
from typing import Optional


@dataclass
class FormatOverride:
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    size: Optional[float] = None
    color: Optional[Color] = None
    family: Optional[str] = None


@dataclass
class FontChoice:
    fontname: str
    fontbuffer: Optional[bytes]
    size: float
    color: Color
    used_fallback: bool


_SERIF_HINTS = ('times', 'georgia', 'garamond', 'serif', 'cambria', 'book')
_BASE14_SANS = {(False, False): 'helv', (False, True): 'heit', (True, False): 'hebo', (True, True): 'hebi'}
_BASE14_SERIF = {(False, False): 'tiro', (False, True): 'tiit', (True, False): 'tibo', (True, True): 'tibi'}


def _normalize_family(name: str) -> dict:
    base = re.sub(r'^[A-Z]{6}\+', '', name)
    lowered = base.lower()
    bold = 'bold' in lowered
    italic = 'italic' in lowered or 'oblique' in lowered
    root = re.sub(r'(bold|italic|oblique|regular|mt|ps)', '', lowered)
    root = re.sub(r'[^a-z0-9]', '', root)
    return {'root': root, 'bold': bold, 'italic': italic}


def _embedded_font_buffer(doc: fitz.Document, page: fitz.Page, family_hint: Optional[str],
                           bold: bool, italic: bool) -> Tuple[Optional[str], Optional[bytes]]:
    if not family_hint:
        return None, None
    target = _normalize_family(family_hint)['root']
    for xref, _ext, _ftype, basefont, name, _encoding in page.get_fonts():
        for candidate in (basefont, name):
            norm = _normalize_family(candidate)
            if norm['root'] != target or norm['bold'] != bold or norm['italic'] != italic:
                continue
            try:
                info = doc.extract_font(xref)
            except Exception:
                continue
            buffer = info[-1] if info else None
            if buffer:
                return f'EF{xref}', buffer
    return None, None


def resolve_font(doc: fitz.Document, page: fitz.Page, span: Optional[TextSpan],
                  override: Optional[FormatOverride]) -> FontChoice:
    override = override or FormatOverride()
    bold = override.bold if override.bold is not None else (span.bold if span else False)
    italic = override.italic if override.italic is not None else (span.italic if span else False)
    size = override.size if override.size is not None else (span.size if span else 12.0)
    color = override.color if override.color is not None else (span.color if span else (0.0, 0.0, 0.0))
    family_hint = override.family if override.family else (span.font_name if span else None)

    fontname, fontbuffer = _embedded_font_buffer(doc, page, family_hint, bold, italic)
    if fontbuffer:
        return FontChoice(fontname, fontbuffer, size, color, used_fallback=False)

    serifed = any(hint in (family_hint or '').lower() for hint in _SERIF_HINTS)
    table = _BASE14_SERIF if serifed else _BASE14_SANS
    return FontChoice(table[(bold, italic)], None, size, color, used_fallback=True)
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -k resolve_font -v`
Expected: PASS (ou SKIPPED para `test_resolve_font_reuses_embedded_font_when_available` se o sistema não
tiver `C:\Windows\Fonts\arial.ttf`)

- [ ] **Step 5: Commit**

```bash
git add pdf_editor.py tests/test_pdf_editor.py
git commit -m "feat: resolucao de fonte com reuso de fonte embutida e fallback base14"
```

---

### Task 3: Trocar e apagar texto (redação + reinserção)

**Files:**
- Modify: `pdf_editor.py`
- Test: `tests/test_pdf_editor.py`

**Interfaces:**
- Consumes: `TextSpan`, `FormatOverride`, `resolve_font` (Tasks 1–2).
- Produces: `replace_span_text(doc: fitz.Document, page: fitz.Page, span: TextSpan, new_text: str, override: Optional[FormatOverride] = None) -> FontChoice`.

- [ ] **Step 1: Escrever os testes que falham**

Add to `tests/test_pdf_editor.py`:

```python
from pdf_editor import replace_span_text


def test_replace_span_text_changes_only_target_span(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    replace_span_text(doc, page, span, 'Texto trocado')
    full_text = page.get_text()
    doc.close()
    assert 'Texto trocado' in full_text
    assert 'Ola mundo' not in full_text
    assert 'Segunda linha de teste' in full_text


def test_replace_span_text_with_empty_string_deletes(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    replace_span_text(doc, page, span, '')
    full_text = page.get_text()
    doc.close()
    assert 'Ola mundo' not in full_text
    assert 'Segunda linha de teste' in full_text
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -k replace_span_text -v`
Expected: FAIL com `ImportError: cannot import name 'replace_span_text'`

- [ ] **Step 3: Implementar em `pdf_editor.py`**

Add:

```python
def replace_span_text(doc: fitz.Document, page: fitz.Page, span: TextSpan, new_text: str,
                       override: Optional[FormatOverride] = None) -> FontChoice:
    page.add_redact_annot(fitz.Rect(span.bbox), fill=(1, 1, 1))
    page.apply_redactions()
    if not new_text:
        return FontChoice('', None, span.size, span.color, used_fallback=False)
    choice = resolve_font(doc, page, span, override)
    if choice.fontbuffer:
        page.insert_font(fontname=choice.fontname, fontbuffer=choice.fontbuffer)
    page.insert_text(span.origin, new_text, fontname=choice.fontname,
                      fontsize=choice.size, color=choice.color)
    return choice
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -k replace_span_text -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pdf_editor.py tests/test_pdf_editor.py
git commit -m "feat: troca e apaga texto de um span via redacao e reinsercao"
```

---

### Task 4: Adicionar texto novo em área livre

**Files:**
- Modify: `pdf_editor.py`
- Test: `tests/test_pdf_editor.py`

**Interfaces:**
- Consumes: `FormatOverride`, `resolve_font` (Task 2).
- Produces: `insert_free_text(doc: fitz.Document, page: fitz.Page, point: Tuple[float, float], text: str, override: FormatOverride) -> FontChoice`.

- [ ] **Step 1: Escrever o teste que falha**

Add to `tests/test_pdf_editor.py`:

```python
from pdf_editor import FormatOverride as _FO  # já importado acima; reaproveita o nome existente
from pdf_editor import insert_free_text


def test_insert_free_text_adds_without_touching_existing_spans(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    page = doc[0]
    before = page.get_text()
    insert_free_text(doc, page, (72, 700), 'Texto novo', FormatOverride(size=12.0, color=(0, 0, 0)))
    after = page.get_text()
    doc.close()
    assert 'Texto novo' in after
    assert before.strip() in after
```

(Remova a linha duplicada de import `_FO` — mantenha só `from pdf_editor import FormatOverride,
insert_free_text` junto do bloco de imports já existente no topo do arquivo de teste.)

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py::test_insert_free_text_adds_without_touching_existing_spans -v`
Expected: FAIL com `ImportError: cannot import name 'insert_free_text'`

- [ ] **Step 3: Implementar em `pdf_editor.py`**

Add:

```python
def insert_free_text(doc: fitz.Document, page: fitz.Page, point: Tuple[float, float],
                      text: str, override: FormatOverride) -> FontChoice:
    choice = resolve_font(doc, page, None, override)
    if choice.fontbuffer:
        page.insert_font(fontname=choice.fontname, fontbuffer=choice.fontbuffer)
    page.insert_text(point, text, fontname=choice.fontname, fontsize=choice.size, color=choice.color)
    return choice
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py::test_insert_free_text_adds_without_touching_existing_spans -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pdf_editor.py tests/test_pdf_editor.py
git commit -m "feat: insere texto novo em area livre da pagina"
```

---

### Task 5: Abertura segura e salvamento em cópia nova

**Files:**
- Modify: `pdf_editor.py`
- Test: `tests/test_pdf_editor.py`

**Interfaces:**
- Produces: `PDFEditError(Exception)`; `open_for_edit(path: str) -> fitz.Document`;
  `save_copy(doc: fitz.Document, original_path: str) -> Path`.

- [ ] **Step 1: Escrever os testes que falham**

Add to `tests/test_pdf_editor.py`:

```python
import hashlib

from pdf_editor import PDFEditError, open_for_edit, save_copy


def test_open_for_edit_rejects_encrypted_pdf(tmp_path):
    path = tmp_path / 'protegido.pdf'
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='dono', user_pw='usuario')
    doc.close()
    with pytest.raises(PDFEditError):
        open_for_edit(str(path))


def test_open_for_edit_rejects_corrupted_file(tmp_path):
    path = tmp_path / 'corrompido.pdf'
    path.write_bytes(b'nao e um pdf de verdade')
    with pytest.raises(PDFEditError):
        open_for_edit(str(path))


def test_save_copy_never_overwrites_original(sample_pdf):
    original_bytes_before = sample_pdf.read_bytes()
    doc = open_for_edit(str(sample_pdf))
    page = doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    replace_span_text(doc, page, span, 'Editado')
    target = save_copy(doc, str(sample_pdf))
    doc.close()
    assert target != sample_pdf
    assert target.exists()
    assert hashlib.sha256(sample_pdf.read_bytes()).hexdigest() == hashlib.sha256(original_bytes_before).hexdigest()
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -k "open_for_edit or save_copy" -v`
Expected: FAIL com `ImportError: cannot import name 'open_for_edit'`

- [ ] **Step 3: Implementar em `pdf_editor.py`**

Add:

```python
from pathlib import Path


class PDFEditError(Exception):
    pass


def open_for_edit(path: str) -> fitz.Document:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise PDFEditError(f'Nao foi possivel abrir o PDF: {exc}') from exc
    if doc.is_encrypted:
        doc.close()
        raise PDFEditError('Este PDF e protegido por senha e nao pode ser editado.')
    if not doc.permissions & fitz.PDF_PERM_MODIFY:
        doc.close()
        raise PDFEditError('Este PDF nao permite edicao (restricao de permissao do arquivo).')
    return doc


def save_copy(doc: fitz.Document, original_path: str) -> Path:
    original = Path(original_path)
    target = original.with_name(f'{original.stem}_editado{original.suffix}')
    counter = 2
    while target.exists():
        target = original.with_name(f'{original.stem}_editado_{counter}{original.suffix}')
        counter += 1
    doc.save(str(target))
    return target
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -k "open_for_edit or save_copy" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pdf_editor.py tests/test_pdf_editor.py
git commit -m "feat: abertura segura de PDF protegido/corrompido e salvamento em copia nova"
```

---

### Task 6: Sessão de edição com desfazer

**Files:**
- Modify: `pdf_editor.py`
- Test: `tests/test_pdf_editor.py`

**Interfaces:**
- Consumes: `fitz.Document` aberto via `open_for_edit` (Task 5).
- Produces: `EditSession` (classe: `doc: fitz.Document`, `snapshot() -> None`, `undo() -> bool`,
  `discard_last_snapshot() -> None`).

- [ ] **Step 1: Escrever o teste que falha**

Add to `tests/test_pdf_editor.py`:

```python
from pdf_editor import EditSession


def test_undo_reverts_last_edit(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    session = EditSession(doc)
    page = session.doc[0]
    span = next(s for s in spans_for_page(page) if s.text.strip() == 'Ola mundo')
    session.snapshot()
    replace_span_text(session.doc, page, span, 'Texto trocado')
    assert 'Texto trocado' in session.doc[0].get_text()
    assert session.undo() is True
    assert 'Ola mundo' in session.doc[0].get_text()
    assert 'Texto trocado' not in session.doc[0].get_text()
    assert session.undo() is False
    session.doc.close()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py::test_undo_reverts_last_edit -v`
Expected: FAIL com `ImportError: cannot import name 'EditSession'`

- [ ] **Step 3: Implementar em `pdf_editor.py`**

Add:

```python
class EditSession:
    def __init__(self, doc: fitz.Document):
        self.doc = doc
        self._undo_stack: List[bytes] = []

    def snapshot(self) -> None:
        self._undo_stack.append(self.doc.tobytes())

    def discard_last_snapshot(self) -> None:
        if self._undo_stack:
            self._undo_stack.pop()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        data = self._undo_stack.pop()
        self.doc.close()
        self.doc = fitz.open(stream=data, filetype='pdf')
        return True
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py::test_undo_reverts_last_edit -v`
Expected: PASS

- [ ] **Step 5: Rodar a suíte inteira do motor**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -v`
Expected: todos os testes PASS (exceto o de fonte embutida, SKIPPED se Arial não existir no sistema)

- [ ] **Step 6: Commit**

```bash
git add pdf_editor.py tests/test_pdf_editor.py
git commit -m "feat: sessao de edicao com desfazer via snapshot do documento"
```

---

### Task 7: Canvas de página com hit-test de spans

**Files:**
- Create: `pdf_editor_view.py`
- Test: `tests/test_pdf_editor.py`

**Interfaces:**
- Consumes: `TextSpan` (Task 1).
- Produces: `span_at_point(spans: List[TextSpan], point: Tuple[float, float]) -> Optional[TextSpan]`;
  `PageCanvas` (QLabel: `zoom: float`, `spans: List[TextSpan]`, `add_mode: bool`,
  `show_page(page, spans) -> None`, `set_add_mode(enabled) -> None`,
  sinais `span_clicked(object)` e `free_area_clicked(float, float)`); `PageScrollArea` (QScrollArea com
  `.canvas: PageCanvas`).

- [ ] **Step 1: Escrever o teste que falha (hit-test puro, sem Qt)**

Add to `tests/test_pdf_editor.py`:

```python
from pdf_editor_view import span_at_point


def test_span_at_point_finds_span_containing_point(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    spans = spans_for_page(doc[0])
    doc.close()
    target = next(s for s in spans if s.text.strip() == 'Ola mundo')
    x0, y0, x1, y1 = target.bbox
    midpoint = ((x0 + x1) / 2, (y0 + y1) / 2)
    found = span_at_point(spans, midpoint)
    assert found is target


def test_span_at_point_returns_none_outside_any_span(sample_pdf):
    doc = fitz.open(str(sample_pdf))
    spans = spans_for_page(doc[0])
    doc.close()
    assert span_at_point(spans, (10, 780)) is None
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -k span_at_point -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pdf_editor_view'`

- [ ] **Step 3: Criar `pdf_editor_view.py`**

```python
from __future__ import annotations

from typing import List, Optional, Tuple

import fitz
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QLabel, QScrollArea, QWidget

from pdf_editor import TextSpan

DEFAULT_ZOOM = 1.5


def span_at_point(spans: List[TextSpan], point: Tuple[float, float]) -> Optional[TextSpan]:
    x, y = point
    for span in spans:
        x0, y0, x1, y1 = span.bbox
        if x0 <= x <= x1 and y0 <= y <= y1:
            return span
    return None


class PageCanvas(QLabel):
    span_clicked = pyqtSignal(object)             # TextSpan
    free_area_clicked = pyqtSignal(float, float)   # ponto em coordenadas do documento (pontos PDF)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.zoom = DEFAULT_ZOOM
        self.spans: List[TextSpan] = []
        self.add_mode = False

    def show_page(self, page: fitz.Page, spans: List[TextSpan]) -> None:
        self.spans = spans
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        self.setPixmap(QPixmap.fromImage(image.copy()))
        self.setFixedSize(pix.width, pix.height)

    def set_add_mode(self, enabled: bool) -> None:
        self.add_mode = enabled

    def mousePressEvent(self, event: QMouseEvent) -> None:
        doc_x = event.position().x() / self.zoom
        doc_y = event.position().y() / self.zoom
        if self.add_mode:
            self.free_area_clicked.emit(doc_x, doc_y)
            return
        span = span_at_point(self.spans, (doc_x, doc_y))
        if span:
            self.span_clicked.emit(span)


class PageScrollArea(QScrollArea):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.canvas = PageCanvas()
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)
```

(`image.copy()` desacopla o `QImage` do buffer `pix.samples`, que é liberado quando `pix` sai de escopo —
sem o `.copy()` o pixmap exibido pode corromper.)

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `py -3.14 -m pytest tests/test_pdf_editor.py -k span_at_point -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pdf_editor_view.py tests/test_pdf_editor.py
git commit -m "feat: canvas de pagina com renderizacao e hit-test de spans"
```

---

### Task 8: Popup de edição com barra de formatação

**Files:**
- Modify: `pdf_editor_view.py`

**Interfaces:**
- Consumes: `TextSpan`, `FormatOverride` (Tasks 1, 2).
- Produces: `SpanEditPopup` (QWidget: `open_for_span(span, global_pos) -> None`,
  `open_for_new_text(global_pos) -> None`, sinais `confirmed(object, str, object)` — `(span_ou_None,
  texto_novo, FormatOverride)` — e `cancelled()`).

- [ ] **Step 1: Implementar `SpanEditPopup` em `pdf_editor_view.py`**

Add:

```python
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QColorDialog, QFontComboBox, QHBoxLayout, QLineEdit, QPushButton,
    QSpinBox, QToolButton, QVBoxLayout,
)

from pdf_editor import FormatOverride


class SpanEditPopup(QWidget):
    confirmed = pyqtSignal(object, str, object)   # span (ou None), texto novo, FormatOverride
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Popup)
        self._span: Optional[TextSpan] = None
        self._color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.text_input = QLineEdit()
        self.text_input.returnPressed.connect(self._confirm)
        layout.addWidget(self.text_input)

        toolbar = QHBoxLayout()
        self.bold_btn = QToolButton()
        self.bold_btn.setText('N')
        self.bold_btn.setCheckable(True)
        self.italic_btn = QToolButton()
        self.italic_btn.setText('I')
        self.italic_btn.setCheckable(True)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 96)
        self.size_spin.setValue(12)
        self.font_combo = QFontComboBox()
        self.color_btn = QPushButton('Cor')
        self.color_btn.clicked.connect(self._pick_color)
        toolbar.addWidget(self.bold_btn)
        toolbar.addWidget(self.italic_btn)
        toolbar.addWidget(self.size_spin)
        toolbar.addWidget(self.font_combo)
        toolbar.addWidget(self.color_btn)
        layout.addLayout(toolbar)

        buttons = QHBoxLayout()
        ok_btn = QPushButton('OK')
        ok_btn.clicked.connect(self._confirm)
        cancel_btn = QPushButton('Cancelar')
        cancel_btn.clicked.connect(self._cancel)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def open_for_span(self, span: TextSpan, global_pos) -> None:
        self._span = span
        self.text_input.setText(span.text)
        self.bold_btn.setChecked(span.bold)
        self.italic_btn.setChecked(span.italic)
        self.size_spin.setValue(int(span.size))
        self.font_combo.setCurrentFont(QFont(span.font_name))
        self._color = span.color
        self.move(global_pos)
        self.show()
        self.text_input.setFocus()
        self.text_input.selectAll()

    def open_for_new_text(self, global_pos) -> None:
        self._span = None
        self.text_input.clear()
        self.bold_btn.setChecked(False)
        self.italic_btn.setChecked(False)
        self.size_spin.setValue(12)
        self._color = (0.0, 0.0, 0.0)
        self.move(global_pos)
        self.show()
        self.text_input.setFocus()

    def _pick_color(self) -> None:
        r, g, b = (int(c * 255) for c in self._color)
        chosen = QColorDialog.getColor(QColor(r, g, b), self)
        if chosen.isValid():
            self._color = (chosen.redF(), chosen.greenF(), chosen.blueF())

    def _confirm(self) -> None:
        override = FormatOverride(
            bold=self.bold_btn.isChecked(),
            italic=self.italic_btn.isChecked(),
            size=float(self.size_spin.value()),
            color=self._color,
            family=self.font_combo.currentFont().family(),
        )
        self.confirmed.emit(self._span, self.text_input.text(), override)
        self.hide()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.hide()
```

- [ ] **Step 2: Verificar que o módulo carrega sem erro**

Run: `py -3.14 -c "import pdf_editor_view"`
Expected: sem saída, exit code 0

- [ ] **Step 3: Commit**

```bash
git add pdf_editor_view.py
git commit -m "feat: popup de edicao de span com barra de formatacao"
```

---

### Task 9: Integrar o modo "Editar PDF" em `gui.py`

**Files:**
- Modify: `gui.py`
- Test: `tests/test_gui_edit_mode.py`

**Interfaces:**
- Consumes: tudo de `pdf_editor.py` (Tasks 1–6) e `pdf_editor_view.py` (Tasks 7–8).

- [ ] **Step 1: Escrever o teste headless que falha**

Create `tests/test_gui_edit_mode.py`:

```python
from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from gui import MainWindow


def test_edit_mode_renders_first_page(qtbot, sample_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(sample_pdf)
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)
    assert window.edit_session is not None
    assert window.stack.currentIndex() == 1
    assert len(window.edit_scroll.canvas.spans) > 0
    window.close()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `py -3.14 -m pytest tests/test_gui_edit_mode.py -v`
Expected: FAIL com `AttributeError: 'MainWindow' object has no attribute 'edit_mode_button'`

- [ ] **Step 3: Adicionar imports e estado em `gui.py`**

At the top imports section (`gui.py:1-25`), update:

```python
from typing import Optional, Tuple
```

and add, right after the existing `from utils import clean_text, sanitize_error_message` line:

```python
from pdf_editor import (
    EditSession, FormatOverride, PDFEditError, TextSpan,
    insert_free_text, open_for_edit, replace_span_text, save_copy, spans_for_page,
)
from pdf_editor_view import PageScrollArea, SpanEditPopup
```

and update the `PyQt6.QtWidgets` import block (`gui.py:16-20`) to include `QStackedWidget`:

```python
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QProgressBar, QSlider, QSpinBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)
```

In `MainWindow.__init__` (`gui.py:200-211`), after `self._last_dir = str(Path.home())`, add:

```python
self.edit_session: Optional[EditSession] = None
self.edit_page_index = 0
self._pending_new_point: Tuple[float, float] = (0.0, 0.0)
```

- [ ] **Step 4: Rodar o teste e confirmar que ainda falha (esperado, faltam os widgets)**

Run: `py -3.14 -m pytest tests/test_gui_edit_mode.py -v`
Expected: FAIL com `AttributeError: 'MainWindow' object has no attribute 'edit_mode_button'`

- [ ] **Step 5: Trocar `_build_ui` para usar `QStackedWidget` e adicionar o botão de modo**

Replace `_build_ui` (`gui.py:221-230`):

```python
def _build_ui(self) -> None:
    root = QWidget()
    root.setObjectName('Root')
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(self._build_header())
    self.stack = QStackedWidget()
    self.stack.addWidget(self._build_editor())     # indice 0: leitura
    self.stack.addWidget(self._build_edit_view())   # indice 1: edicao
    layout.addWidget(self.stack, 1)
    layout.addWidget(self._build_footer())
    self.setCentralWidget(root)
```

In `_build_header` (`gui.py:232-281`), after the line
`self.about_button.clicked.connect(self._show_about)`, add:

```python
self.edit_mode_button = QPushButton('Editar PDF')
self.edit_mode_button.setObjectName('HeaderBtn')
self.edit_mode_button.setCheckable(True)
self.edit_mode_button.setEnabled(False)
self.edit_mode_button.setFixedHeight(36)
self.edit_mode_button.toggled.connect(self._on_edit_mode_toggled)
```

and add `hbox.addWidget(self.edit_mode_button)` right before `hbox.addWidget(self._vline())` that precedes
`self.export_button` (so the new button sits next to `close_button`).

- [ ] **Step 6: Implementar `_build_edit_view` e os handlers de edição**

Add these methods to `MainWindow` (near `_build_footer`, e.g. right after it):

```python
def _build_edit_view(self) -> QWidget:
    container = QWidget()
    vbox = QVBoxLayout(container)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(0)

    toolbar = QFrame()
    toolbar.setObjectName('EditToolbar')
    hbox = QHBoxLayout(toolbar)
    self.edit_prev_button = QPushButton('◀')
    self.edit_prev_button.clicked.connect(lambda: self._go_edit_page(-1))
    self.edit_page_label = QLabel('—')
    self.edit_next_button = QPushButton('▶')
    self.edit_next_button.clicked.connect(lambda: self._go_edit_page(1))
    self.add_text_button = QPushButton('Adicionar texto')
    self.add_text_button.setCheckable(True)
    self.add_text_button.toggled.connect(self._toggle_add_mode)
    self.edit_undo_button = QPushButton('Desfazer')
    self.edit_undo_button.clicked.connect(self._edit_undo)
    self.edit_save_button = QPushButton('Salvar cópia')
    self.edit_save_button.clicked.connect(self._save_edited_copy)
    hbox.addWidget(self.edit_prev_button)
    hbox.addWidget(self.edit_page_label)
    hbox.addWidget(self.edit_next_button)
    hbox.addSpacing(12)
    hbox.addWidget(self.add_text_button)
    hbox.addWidget(self.edit_undo_button)
    hbox.addStretch(1)
    hbox.addWidget(self.edit_save_button)
    vbox.addWidget(toolbar)

    self.edit_scroll = PageScrollArea()
    self.edit_scroll.canvas.span_clicked.connect(self._on_span_clicked)
    self.edit_scroll.canvas.free_area_clicked.connect(self._on_free_area_clicked)
    vbox.addWidget(self.edit_scroll, 1)

    self.edit_popup = SpanEditPopup(self)
    self.edit_popup.confirmed.connect(self._on_popup_confirmed)

    return container

def _on_edit_mode_toggled(self, checked: bool) -> None:
    if checked:
        self._enter_edit_mode()
    else:
        self._exit_edit_mode()

def _enter_edit_mode(self) -> None:
    if not self.current_file:
        return
    try:
        doc = open_for_edit(self.current_file)
    except PDFEditError as exc:
        QMessageBox.warning(self, 'Não é possível editar', str(exc))
        self.edit_mode_button.setChecked(False)
        return
    self.edit_session = EditSession(doc)
    self.edit_page_index = 0
    self.stack.setCurrentIndex(1)
    self._render_edit_page()

def _exit_edit_mode(self) -> None:
    self.stack.setCurrentIndex(0)
    if self.edit_session:
        self.edit_session.doc.close()
        self.edit_session = None

def _render_edit_page(self) -> None:
    if not self.edit_session:
        return
    page = self.edit_session.doc[self.edit_page_index]
    spans = spans_for_page(page)
    self.edit_scroll.canvas.show_page(page, spans)
    self.edit_page_label.setText(
        f'Página {self.edit_page_index + 1} de {self.edit_session.doc.page_count}'
    )

def _go_edit_page(self, delta: int) -> None:
    if not self.edit_session:
        return
    new_index = self.edit_page_index + delta
    if 0 <= new_index < self.edit_session.doc.page_count:
        self.edit_page_index = new_index
        self._render_edit_page()

def _toggle_add_mode(self, checked: bool) -> None:
    self.edit_scroll.canvas.set_add_mode(checked)

def _on_span_clicked(self, span: TextSpan) -> None:
    x, y = span.origin
    local = QPoint(int(x * self.edit_scroll.canvas.zoom), int(y * self.edit_scroll.canvas.zoom))
    self.edit_popup.open_for_span(span, self.edit_scroll.canvas.mapToGlobal(local))

def _on_free_area_clicked(self, x: float, y: float) -> None:
    self._pending_new_point = (x, y)
    local = QPoint(int(x * self.edit_scroll.canvas.zoom), int(y * self.edit_scroll.canvas.zoom))
    self.edit_popup.open_for_new_text(self.edit_scroll.canvas.mapToGlobal(local))

def _on_popup_confirmed(self, span, new_text: str, override: FormatOverride) -> None:
    if not self.edit_session:
        return
    page = self.edit_session.doc[self.edit_page_index]
    self.edit_session.snapshot()
    try:
        if span is not None:
            choice = replace_span_text(self.edit_session.doc, page, span, new_text, override)
        else:
            choice = insert_free_text(self.edit_session.doc, page, self._pending_new_point, new_text, override)
    except Exception as exc:
        self.edit_session.discard_last_snapshot()
        self._show_error(sanitize_error_message(str(exc)))
        return
    self._render_edit_page()
    if choice.used_fallback:
        self.status_label.setText(
            'Edição aplicada com fonte aproximada (a fonte original não pôde ser reutilizada).'
        )
    else:
        self.status_label.setText('Edição aplicada.')

def _edit_undo(self) -> None:
    if self.edit_session and self.edit_session.undo():
        self._render_edit_page()
    else:
        self.status_label.setText('Nada para desfazer.')

def _save_edited_copy(self) -> None:
    if not self.edit_session or not self.current_file:
        return
    try:
        target = save_copy(self.edit_session.doc, self.current_file)
    except OSError as exc:
        self._show_error(sanitize_error_message(str(exc)))
        return
    QMessageBox.information(self, 'Salvo', f'Cópia editada salva em:\n{target}')
```

- [ ] **Step 7: Habilitar/desabilitar o botão de modo conforme o documento aberto**

In `_document_loaded` (`gui.py:512-531`), right after the line
`self._set_reading_buttons(True)`, add:

```python
self.edit_mode_button.setEnabled(kind == 'PDF')
```

In `close_document` (`gui.py:533-550`), right after `self._set_reading_buttons(False)`, add:

```python
self.edit_mode_button.setEnabled(False)
self.edit_mode_button.setChecked(False)
```

- [ ] **Step 8: Rodar o teste headless e confirmar que passa**

Run: `py -3.14 -m pytest tests/test_gui_edit_mode.py -v`
Expected: PASS

- [ ] **Step 9: Rodar a suíte inteira**

Run: `py -3.14 -m pytest tests -v`
Expected: todos PASS (ou SKIPPED apenas o teste de fonte embutida, se aplicável)

- [ ] **Step 10: Commit**

```bash
git add gui.py tests/test_gui_edit_mode.py
git commit -m "feat: integra o modo Editar PDF na janela principal"
```

---

### Task 10: Verificação manual end-to-end

**Files:**
- Nenhum arquivo novo — checklist manual sobre o app já implementado.

- [ ] **Step 1: Rodar o app**

Run: `py -3.14 main.py`
Expected: janela abre normalmente, modo leitura funcionando como antes.

- [ ] **Step 2: Checklist manual**

Com um PDF nativo real (texto digital, não escaneado):

1. Abrir o PDF → botão "Editar PDF" fica habilitado.
2. Clicar "Editar PDF" → a página aparece renderizada, navegação ◀/▶ funciona em PDFs de várias páginas.
3. Clicar num trecho de texto → popup abre com o texto atual e a formatação atual preenchidos.
4. Trocar o texto e confirmar → o trecho antigo desaparece, o novo aparece na mesma posição, o resto da
   página permanece intacto.
5. Clicar noutro trecho, apagar (deixar vazio) e confirmar → o trecho some, resto intacto.
6. Ativar "Adicionar texto", clicar numa área em branco, digitar e confirmar → texto novo aparece só ali.
7. Editar um trecho mudando negrito/itálico/tamanho/cor/fonte → formatação aplicada visivelmente.
8. Clicar "Desfazer" após uma edição → reverte para o estado anterior.
9. Clicar "Salvar cópia" → arquivo `<nome>_editado.pdf` é criado ao lado do original; abrir o original
   separadamente e confirmar que **não foi alterado**.
10. Abrir a cópia salva num leitor de PDF externo e comparar visualmente com o original — só as edições
    pretendidas devem aparecer diferentes.

- [ ] **Step 3: Se algum problema for encontrado, corrigir e commitar**

Se o checklist revelar um bug, corrija o arquivo relevante (`pdf_editor.py`, `pdf_editor_view.py` ou
`gui.py`), rode `py -3.14 -m pytest tests -v` para confirmar que nada quebrou, e commit:

```bash
git add -A
git commit -m "fix: ajuste encontrado na verificacao manual do editor de PDF"
```

Se nenhum problema for encontrado, nenhum commit é necessário neste passo.
