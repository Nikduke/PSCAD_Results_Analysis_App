# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


SLIM_EXCLUDES = [
    'tkinter',
    'pytest',
    'tests',
    'test',
    'pydoc',
    'doctest',
    'scipy',
    'numpy.f2py',
    'IPython',
    'jupyter',
    'notebook',
    'PyQt5',
    'PyQt6',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtDesigner',
    'PySide6.QtHelp',
    'PySide6.QtMultimedia',
    'PySide6.QtNetwork',
    'PySide6.QtNetworkAuth',
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtPositioning',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtSerialPort',
    'PySide6.QtSql',
    'PySide6.QtSvgWidgets',
    'PySide6.QtWebChannel',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PIL._avif',
    'PIL.AvifImagePlugin',
]


DROP_BUNDLE_NAMES = {
    'PySide6\\opengl32sw.dll',
    'PySide6\\Qt6Network.dll',
    'PySide6\\Qt6OpenGL.dll',
    'PySide6\\Qt6Pdf.dll',
    'PySide6\\Qt6Qml.dll',
    'PySide6\\Qt6QmlModels.dll',
    'PySide6\\Qt6QmlMeta.dll',
    'PySide6\\Qt6QmlWorkerScript.dll',
    'PySide6\\Qt6Quick.dll',
    'PySide6\\Qt6QuickControls2.dll',
    'PySide6\\Qt6QuickTemplates2.dll',
    'PySide6\\Qt6Svg.dll',
    'PySide6\\Qt6VirtualKeyboard.dll',
    'PySide6\\QtNetwork.pyd',
    'PySide6\\QtOpenGL.pyd',
    'PySide6\\QtOpenGLWidgets.pyd',
    'PySide6\\QtPdf.pyd',
    'PySide6\\QtPdfWidgets.pyd',
    'PySide6\\QtQml.pyd',
    'PySide6\\QtQuick.pyd',
    'PySide6\\QtQuickWidgets.pyd',
}

DROP_BUNDLE_PREFIXES = (
    'PySide6\\translations\\',
    'PySide6\\qml\\',
    'PySide6\\plugins\\qmltooling\\',
    'PySide6\\plugins\\sceneparsers\\',
    'PySide6\\plugins\\sqldrivers\\',
    'matplotlib\\mpl-data\\fonts\\afm\\',
    'matplotlib\\mpl-data\\fonts\\pdfcorefonts\\',
    'matplotlib\\mpl-data\\images\\',
    'matplotlib\\mpl-data\\sample_data\\',
    'matplotlib\\mpl-data\\stylelib\\',
)

DROP_BUNDLE_CONTAINS = (
    'matplotlib\\mpl-data\\fonts\\ttf\\DejaVuSansDisplay.ttf',
    'matplotlib\\mpl-data\\fonts\\ttf\\DejaVuSansMono',
    'matplotlib\\mpl-data\\fonts\\ttf\\DejaVuSerif',
    'matplotlib\\mpl-data\\fonts\\ttf\\STIX',
    'matplotlib\\mpl-data\\fonts\\ttf\\cmb10.ttf',
    'matplotlib\\mpl-data\\fonts\\ttf\\cmex10.ttf',
    'matplotlib\\mpl-data\\fonts\\ttf\\cmmi10.ttf',
    'matplotlib\\mpl-data\\fonts\\ttf\\cmr10.ttf',
    'matplotlib\\mpl-data\\fonts\\ttf\\cmss10.ttf',
    'matplotlib\\mpl-data\\fonts\\ttf\\cmsy10.ttf',
    'matplotlib\\mpl-data\\fonts\\ttf\\cmtt10.ttf',
    'PIL\\_avif',
    'PIL\\_imagingcms',
    'PIL\\_imagingmath',
    'PIL\\_imagingtk',
    'PIL\\_webp',
)

DROP_QT_PLUGINS = {
    'PySide6\\plugins\\generic\\qtuiotouchplugin.dll',
    'PySide6\\plugins\\iconengines\\qsvgicon.dll',
    'PySide6\\plugins\\imageformats\\qgif.dll',
    'PySide6\\plugins\\imageformats\\qicns.dll',
    'PySide6\\plugins\\imageformats\\qjpeg.dll',
    'PySide6\\plugins\\imageformats\\qpdf.dll',
    'PySide6\\plugins\\imageformats\\qsvg.dll',
    'PySide6\\plugins\\imageformats\\qtga.dll',
    'PySide6\\plugins\\imageformats\\qtiff.dll',
    'PySide6\\plugins\\imageformats\\qwbmp.dll',
    'PySide6\\plugins\\imageformats\\qwebp.dll',
    'PySide6\\plugins\\platforminputcontexts\\qtvirtualkeyboardplugin.dll',
    'PySide6\\plugins\\platforms\\qdirect2d.dll',
    'PySide6\\plugins\\platforms\\qminimal.dll',
    'PySide6\\plugins\\platforms\\qoffscreen.dll',
}

KEEP_BUNDLE_NAMES = {
    'PySide6\\plugins\\styles\\qmodernwindowsstyle.dll',
    'PySide6\\plugins\\styles\\qwindowsvistastyle.dll',
}


def _normalized_bundle_name(item):
    return item[0].replace('/', '\\')


def _should_drop(item):
    name = _normalized_bundle_name(item)
    lower_name = name.lower()
    if name in KEEP_BUNDLE_NAMES:
        return False
    if name in DROP_BUNDLE_NAMES or name in DROP_QT_PLUGINS:
        return True
    if any(lower_name.startswith(prefix.lower()) for prefix in DROP_BUNDLE_PREFIXES):
        return True
    return any(token.lower() in lower_name for token in DROP_BUNDLE_CONTAINS)


def _without_slim_drops(items):
    return [item for item in items if not _should_drop(item)]


hiddenimports = ['win32com.client', 'pythoncom', 'pywintypes', 'pyexpat']
hiddenimports += collect_submodules('results_analysis_app')
hiddenimports += collect_submodules('pscad_plotter_app_v3')


def _conda_runtime_binaries():
    env_root = Path(sys.executable).resolve().parent
    conda_bin = env_root / 'Library' / 'bin'
    candidates = [
        conda_bin / 'ffi-8.dll',
        conda_bin / 'libbz2.dll',
        conda_bin / 'libcrypto-3-x64.dll',
        conda_bin / 'libexpat.dll',
        conda_bin / 'liblzma.dll',
        conda_bin / 'libssl-3-x64.dll',
        conda_bin / 'sqlite3.dll',
    ]
    return [(str(path), '.') for path in candidates if path.is_file()]


a = Analysis(
    ['src\\results_analysis_app\\__main__.py'],
    pathex=['src'],
    binaries=_conda_runtime_binaries(),
    datas=[('src\\results_analysis_app\\assets\\mpe_app_icon.ico', 'results_analysis_app\\assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=SLIM_EXCLUDES,
    noarchive=False,
    optimize=1,
)
a.binaries = _without_slim_drops(a.binaries)
a.datas = _without_slim_drops(a.datas)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PSCADResultsAnalysis',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\results_analysis_app\\assets\\mpe_app_icon.ico'],
)
