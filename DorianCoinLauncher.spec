# DorianCoinLauncher.spec
# Run:  pyinstaller DorianCoinLauncher.spec
# Output: dist/DorianCoinLauncher.exe

import os

HERE = os.path.dirname(os.path.abspath(SPEC))   # noqa: F821 (SPEC injected by PyInstaller)

datas = [
    # Bundle all DorianCoin Python source files as data so the launcher
    # can run them as subprocesses (node.py, demos, drn_wallet.py, etc.)
    (os.path.join(HERE, "doriancoin", "*.py"),    "doriancoin"),
    (os.path.join(HERE, "doriancoin", "explorer.html"), "doriancoin"),
    (os.path.join(HERE, "doriancoin", "requirements.txt"), "doriancoin"),
]

a = Analysis(                                    # noqa: F821
    [os.path.join(HERE, "doriancoin", "launcher.py")],
    pathex=[os.path.join(HERE, "doriancoin")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "cryptography",
        "cryptography.hazmat.primitives.asymmetric.ec",
        "cryptography.hazmat.primitives.hashes",
        "cryptography.hazmat.primitives.serialization",
        "cryptography.hazmat.backends",
        "flask",
        "requests",
        "sqlite3",
        "hashlib",
        "json",
        "threading",
        "subprocess",
        "webbrowser",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)                                # noqa: F821

exe = EXE(                                       # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DorianCoinLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # keep console window — TUI needs it
    icon=None,
)
