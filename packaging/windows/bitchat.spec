# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for BitChat Windows distributable."""

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Determine repository root and source directories
repo_root = Path.cwd().resolve()
src_dir = repo_root / "src"

# Collect all package data and assets
datas = []
datas += collect_data_files("bitchat")
datas += collect_data_files("textual")

# Ensure textual CSS styles are explicitly bundled
tcss_file = src_dir / "bitchat" / "tui" / "styles" / "app.tcss"
if tcss_file.exists():
    datas.append((str(tcss_file), "bitchat/tui/styles"))

# Collect submodules to prevent dynamic import omissions
hiddenimports = []
hiddenimports += collect_submodules("bitchat")
hiddenimports += collect_submodules("bleak")
hiddenimports += collect_submodules("cryptography")
hiddenimports += collect_submodules("textual")

a = Analysis(
    [str(src_dir / "bitchat" / "__main__.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy", "pytest", "pyright", "ruff"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="bitchat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
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
    upx=False,
    upx_exclude=[],
    name="bitchat",
)
