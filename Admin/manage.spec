# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None

project_dir = os.path.dirname(os.path.abspath(SPEC))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

app_hiddenimports = collect_submodules(
    'app',
    filter=lambda name: not name.startswith('app.tests'),
)
framework_hiddenimports = collect_submodules('framework')

required_hiddenimports = {
    'app.apps',
    'app.management.commands.serve_production',
    'app.middleware',
    'app.utils.JsonLogFormatter',
    'framework.wsgi',
}
discovered_hiddenimports = set(app_hiddenimports + framework_hiddenimports)
missing_hiddenimports = required_hiddenimports - discovered_hiddenimports
if missing_hiddenimports:
    raise RuntimeError(
        'Unable to discover required modules: ' + ', '.join(sorted(missing_hiddenimports))
    )

templates_dir = os.path.join(project_dir, 'templates')
staticfiles_dir = os.path.join(project_dir, 'staticfiles')
project_version_file = os.path.join(project_dir, '..', 'PROJECT_VERSION')
if not os.path.isdir(staticfiles_dir):
    raise RuntimeError(
        'Admin/staticfiles is missing; run "python manage.py collectstatic --noinput" before packaging.'
    )


a = Analysis(
    ['manage.py'],
    pathex=[],
    binaries=[],
    datas=[
        (templates_dir, 'templates'),
        (staticfiles_dir, 'staticfiles'),
        (project_version_file, '.'),
    ],
    hiddenimports=[
        'django.contrib.admin',
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.messages',
        'django.contrib.staticfiles',
        'waitress',
        'whitenoise.middleware',
    ] + app_hiddenimports + framework_hiddenimports,
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
    name='manage',
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='manage',
)
