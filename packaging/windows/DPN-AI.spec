# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the DPN AI v8 Windows desktop executable.

The package deliberately uses onedir rather than onefile. That keeps application
assets inspectable, makes updates/rollback safer, and avoids extracting the full
runtime to a temporary directory on every launch.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]

app_data = collect_data_files("app", include_py_files=False)

# Only immutable application assets are bundled. Mutable local state and credentials
# are intentionally excluded from the package.
datas = [
    (str(ROOT / "VERSION"), "."),
    (str(ROOT / "requirements.txt"), "."),
    (str(ROOT / "app" / "static"), "app/static"),
]

# Include data discovered by package hooks while avoiding duplicate static entries.
for source, target in app_data:
    if "app/static" not in source.replace("\\", "/"):
        datas.append((source, target))

hiddenimports = sorted(set(
    collect_submodules("app")
    + collect_submodules("desktop")
    + [
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ]
))

analysis = Analysis(
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest.mock"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DPN-AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DPN-AI",
)
