# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['splitmarks.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # splitmarks imports textquality inside a try/except so that standalone
    # copies still run without it. Name it here so the frozen binary is not a
    # standalone copy — --check-text must be able to tell a corrupt text layer
    # from a missing one.
    hiddenimports=['textquality'],
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
    a.binaries,
    a.datas,
    [],
    name='splitmarks',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
