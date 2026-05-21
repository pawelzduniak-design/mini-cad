# PyInstaller spec for mini-cad.
#
# Build with:  pyinstaller packaging/mini-cad.spec  (run from the repo root)
# Produces a self-contained folder under dist/mini-cad/ with mini-cad.exe.

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

datas = []
binaries = []
hiddenimports = []

# Heavy native/data-carrying deps that PyInstaller can't trace on its own.
for pkg in ("OCP", "build123d", "cadquery", "shapely"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Ship the toolbar icon PNGs next to the cad_app package.
datas += collect_data_files("cad_app", includes=["assets/icons/*.png"])

a = Analysis(
    ["../cad_app/__main__.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "black", "ruff"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mini-cad",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="mini-cad",
)
