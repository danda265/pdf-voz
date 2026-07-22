# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Tesseract embutido — exe + DLLs + tessdata (por + eng)
        ('tesseract', 'tesseract'),
    ],
    hiddenimports=[
        'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui', 'PyQt6.sip',
        'pygame', 'pygame.mixer',
        'edge_tts', 'edge_tts.communicate', 'edge_tts.list_voices',
        'fitz',
        'docx', 'docx.oxml', 'docx.oxml.ns',
        'pytesseract',
        'asyncio', 'aiohttp', 'aiohttp.connector', 'aiofiles',
        'ssl', 'certifi',
        'numpy', 'PIL', 'PIL.Image',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'IPython', 'jupyter',
        'torch', 'torchvision', 'easyocr',
        'cv2', 'scipy', 'skimage', 'shapely',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDF VOZ',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='assets/icon.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PDF VOZ',
)
