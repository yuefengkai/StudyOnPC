# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
root = Path(SPECPATH)

_cfg = root / "config.json" if (root / "config.json").is_file() else root / "config.example.json"
datas = [
    # Bundle local config when present; otherwise example (build_exe also seeds writable config.json)
    (str(_cfg), "."),
    (str(root / "config.example.json"), "."),
    (str(root / "data" / "banks"), "data/banks"),
    (str(root / "assets"), "assets"),
    (str(root / "scripts" / "set_mute.ps1"), "scripts"),
]
binaries = []
hiddenimports = [
    "pypinyin",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "tkinter",
    "tkinter.messagebox",
    "tkinter.simpledialog",
    "tkinter.ttk",
    "studyonpc",
    "studyonpc.app",
    "studyonpc.bank",
    "studyonpc.config",
    "studyonpc.paths",
    "studyonpc.quiz_ui",
    "studyonpc.pinyin_ui",
    "studyonpc.rules",
    "studyonpc.state",
    "studyonpc.watchdog",
    "studyonpc.win_yt",
    "studyonpc.admin_server",
]

for pkg in ("pypinyin", "PIL"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print("collect_all", pkg, e)

try:
    hiddenimports += collect_submodules("pypinyin")
except Exception:
    pass

a = Analysis(
    [str(root / "studyonpc.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="StudyOnPC",
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StudyOnPC",
)
