# -*- mode: python ; coding: utf-8 -*-
# Folder (onedir) build: distribute the whole dist\OffGasTool folder (zip it or wrap it
# in an installer). Unlike a single-file exe it does not unpack ~250 MB to a temp
# folder on every launch, so it starts faster and trips antivirus scanning far less.

# Libraries the tool never imports that PyInstaller would otherwise pull in.
EXCLUDED_MODULES = [
    'pandas', 'scipy', 'tkinter', 'pytest', '_pytest', 'IPython',
    'PIL._avif', 'PIL.AvifImagePlugin',
    'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf', 'PySide6.QtNetwork',
]

# Qt files the widgets-only GUI never loads. opengl32sw.dll is Qt's software OpenGL
# fallback (~20 MB); QPainter/matplotlib rendering does not use OpenGL. The qpdf image
# plugin and the virtual-keyboard plugin depend on the excluded Pdf/Quick/Qml DLLs.
EXCLUDED_BINARY_PREFIXES = ('opengl32sw', 'qt6quick', 'qt6qml', 'qt6pdf', 'qt6network',
                            'qt6virtualkeyboard', 'qtvirtualkeyboard', 'qpdf')


def _is_excluded_binary(dest_name):
    file_name = dest_name.replace('\\', '/').rsplit('/', 1)[-1].lower()
    return file_name.startswith(EXCLUDED_BINARY_PREFIXES)


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('arup_logo.png', '.')],
    hiddenimports=['spill_poolfire'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)
a.binaries = [entry for entry in a.binaries if not _is_excluded_binary(entry[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OffGasTool',
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
    icon=['jeof_icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='OffGasTool',
)
