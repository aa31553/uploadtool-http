from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).parent.parent

datas = [
    (str(ROOT / "config.example.json"), "."),
]

hiddenimports = (
    collect_submodules("PyQt5")
    + collect_submodules("httpx")
    + collect_submodules("anyio")
)

a = Analysis(
    [str(ROOT / "packaging" / "entrypoints" / "machine_client_entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="uploadtool-client",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="uploadtool-client",
)
