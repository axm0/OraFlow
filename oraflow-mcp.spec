# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['dns.resolver', 'dns.rdatatype', 'dns.rdataclass', 'dns.exception']

# OraFlow runs its own FastMCP server entrypoint directly. Do not ship FastMCP's
# optional CLI/update/skill-sync utilities, which can contain version checks or
# generic download helpers unrelated to OraFlow's runtime.
excluded_modules = [
    'fastmcp.cli',
    'fastmcp.cli.apps_dev',
    'fastmcp.cli.auth',
    'fastmcp.cli.cimd',
    'fastmcp.cli.cli',
    'fastmcp.cli.client',
    'fastmcp.cli.discovery',
    'fastmcp.cli.generate',
    'fastmcp.cli.install',
    'fastmcp.cli.run',
    'fastmcp.cli.tasks',
    'fastmcp.utilities.skills',
]


def is_excluded_data_path(path):
    normalized = str(path).replace('\\', '/').lower()
    excluded_fragments = (
        '/fastmcp/cli/',
        '/fastmcp/utilities/skills.py',
    )
    return any(fragment in normalized for fragment in excluded_fragments)

# Ship the instructions file (and a couple of other top-level docs) inside the
# bundle so server.py can find ORAFLOW_INSTRUCTIONS.md at runtime via
# sys._MEIPASS. The (src, dest) pair places the file at the bundle root.
datas += [
    ('ORAFLOW_INSTRUCTIONS.md', '.'),
    ('customers.toml', '.'),
    ('extensions/vscode/assets/help-topics.toml', '.'),
]

# Many of these libraries load sub-modules dynamically by string (sqlglot
# dialects via read="oracle", pydantic_settings dotenv source, oracledb thick
# loader, etc.) which PyInstaller's static analysis can miss. Use collect_all
# to be exhaustive.
for _pkg in (
    'fastmcp',
    'mcp',
    'pydantic',
    'pydantic_settings',
    'sqlglot',
    'oracledb',
    'cryptography',  # required by oracledb thin-mode auth on legacy verifiers
    'rapidfuzz',
    'dotenv',
    'rich',
    'typer',
    'dns',
    'click',
    'truststore',
):
    try:
        _datas, _bins, _hidden = collect_all(_pkg)
        datas += _datas
        binaries += _bins
        hiddenimports += _hidden
    except Exception:
        # Defensive: a missing optional dep should not abort the build.
        pass

# rapidfuzz exposes a PyInstaller packaging self-test module via its hook. It is
# not needed at runtime and should not ship inside the extension bundle.
hiddenimports = [
    item for item in hiddenimports
    if item != 'rapidfuzz.__pyinstaller.test_rapidfuzz_packaging'
    and not any(item == excluded or item.startswith(excluded + '.') for excluded in excluded_modules)
]
datas = [
    item for item in datas
    if 'test_rapidfuzz_packaging' not in str(item[0])
    and not is_excluded_data_path(item[0])
]


a = Analysis(
    ['src\\oraflow\\server.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='oraflow-mcp',
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
    name='oraflow-mcp',
)
