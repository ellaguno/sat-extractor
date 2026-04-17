# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Collect everything from textual (CSS, widgets, etc.)
textual_datas, textual_binaries, textual_hiddenimports = collect_all('textual')

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=textual_binaries,
    datas=[
        ('satextractor/fiscal/catalogo_sat.toml', 'satextractor/fiscal'),
        ('satextractor/fiscal/reglas_deducciones.toml', 'satextractor/fiscal'),
    ] + textual_datas,
    hiddenimports=[
        'rich',
        'rich.console',
        'rich.text',
        'rich.table',
        'rich.syntax',
        'rich.markdown',
        'rich.pretty',
        'rich.panel',
    ] + textual_hiddenimports + collect_submodules('rich'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='satextractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='satextractor',
)
