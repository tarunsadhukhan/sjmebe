# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_all, collect_data_files

# Collect ALL components (datas, binaries, hiddenimports) for key packages
_collect_packages = [
    'uvicorn', 'fastapi', 'starlette', 'pydantic', 'pydantic_core',
    'sqlalchemy', 'sqlmodel', 'jwt', 'jose', 'passlib', 'cryptography',
    'multipart', 'email_validator', 'openpyxl', 'xlsxwriter',
    'pandas', 'numpy', 'jinja2', 'dotenv', 'bcrypt', 'h11', 'httptools',
    'anyio', 'sniffio', 'pymysql',
]

all_datas = []
all_binaries = []
all_hiddenimports = []
for _pkg in _collect_packages:
    try:
        _d, _b, _h = collect_all(_pkg)
        all_datas += _d
        all_binaries += _b
        all_hiddenimports += _h
    except Exception:
        pass

hiddenimports = [
    'pymysql', 'sqlalchemy.dialects.mysql.pymysql',
    'bcrypt', 'dotenv', 'jwt', 'python_jose', 'python_jose.jwt',
    'jose.jwt', 'jose.jws', 'jose.constants', 'jose.utils',
    'multipart', 'python_multipart',
    'starlette.middleware.trustedhost', 'starlette.responses',
    'email_validator', 'h11', 'httptools', 'websockets',
    'watchfiles', 'anyio', 'sniffio', 'click', 'typing_extensions',
    'sqlmodel',
]
hiddenimports += collect_submodules('src')
hiddenimports += all_hiddenimports


a = Analysis(
    ['run_server.py'],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='vowerp3be',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='vowerp3be',
)
