# lop_editor_onefile.spec
# Build command:
#   pyinstaller lop_editor_onefile.spec
#
# Result:
#   dist/LiesOfPSaveEditor.exe   <-- single self-contained EXE
#
# This is the "large exe" build (PyInstaller onefile style).
# We trim out unused PyQt6 modules like Qt3D, WebEngine, OpenGL, Multimedia.

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# We'll assume you run PyInstaller from the project root
basedir = Path.cwd()

app_name = "LiesOfPSaveEditor"
icon_path = basedir / "app" / "resources" / "app.ico"
resources_dir = basedir / "app" / "resources"

# ------------------------------------------------------------------
# Bundle EVERYTHING in app/resources recursively so uesave.exe,
# csvs, icons, etc. come along for the ride.
#
# In onefile mode, PyInstaller will unpack these to a temp dir
# (sys._MEIPASS/app/resources/...).
# Our updated file_manager knows to look there.
# ------------------------------------------------------------------
datas = []
if resources_dir.exists():
    for root, dirs, files in os.walk(resources_dir):
        for fname in files:
            src_path = Path(root) / fname
            rel_subdir = Path(root).relative_to(resources_dir)
            dest_dir = Path("app", "resources", rel_subdir)
            datas.append((str(src_path), str(dest_dir)))

# If PyQt6 needs extra non-.py resource data (platform plugins etc.), grab them.
datas += collect_data_files("PyQt6", include_py_files=False)

# ------------------------------------------------------------------
# Hidden imports
# We include our own package ('app') so PyInstaller sees all tabs/modules.
# We *don't* force-import every PyQt6 submodule (that can drag in 3D/Web).
# ------------------------------------------------------------------
hiddenimports = []
hiddenimports += collect_submodules("app")

# ------------------------------------------------------------------
# Heavy modules we know we do NOT need.
# - Qt3D*  (3D engine)
# - QtQuick3D
# - QtWebEngine* (Chromium embed)
# - QtOpenGL*, QtMultimedia*, etc. (no video/sound, no 3D pipeline)
# - tkinter / unittest / test harness junk
#
# We keep QtCore, QtGui, QtWidgets, which you actually use.
# ------------------------------------------------------------------
excludes = [
    "PyQt6.Qt3DAnimation",
    "PyQt6.Qt3DCore",
    "PyQt6.Qt3DExtras",
    "PyQt6.Qt3DInput",
    "PyQt6.Qt3DLogic",
    "PyQt6.Qt3DRender",
    "PyQt6.QtQuick3D",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebEngineQuick",
    "PyQt6.QtOpenGL",
    "PyQt6.QtOpenGLWidgets",
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtNetworkAuth",
    "tkinter",
    "unittest",
    "test",
    "pydoc_data",
]

# ------------------------------------------------------------------
# Analysis step
# ------------------------------------------------------------------
a = Analysis(
    [str(basedir / "main.py")],
    pathex=[str(basedir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,  # keep Python code in a .pyz in the bundle
)

# ------------------------------------------------------------------
# PYZ: packs Python modules
# ------------------------------------------------------------------
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

# ------------------------------------------------------------------
# EXE: onefile output
#
# NOTE:
#  - console=False => GUI app (no black console window)
#  - upx=True will compress bootloader/DLLs IF you have UPX installed;
#    if you don't, PyInstaller will just skip the compression.
#
# This is the final standalone EXE you hand out.
# ------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(icon_path) if icon_path.exists() else None,
)
