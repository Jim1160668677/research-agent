# Research Agent Windows desktop build (PyInstaller one-directory mode).

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

# PyInstaller exposes SPECPATH as the directory containing this spec (not the
# spec filename). Taking ``.parent`` here silently points one directory above
# the repository when the project lives in a nested folder.
project_dir = Path(SPECPATH).resolve()
src_dir = project_dir / "src"

hidden_imports = []
for package in (
    "uvicorn",
    "sqlalchemy.dialects.sqlite",
):
    hidden_imports.extend(collect_submodules(package))

hidden_imports.extend([
    "aiosqlite",
    "email_validator",
    "jwt",
    "networkx",
    # pywebview and pystray choose their platform implementation dynamically.
    # Package only native Windows backends; collecting every optional backend
    # pulls mutually exclusive Qt bindings from broad Conda environments.
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "webview.platforms.mshtml",
    "pystray",
    "pystray._win32",
    "PIL.Image",
    "PIL.ImageDraw",
    "openai",
    "anthropic",
    "google.genai",
])

a = Analysis(
    [str(project_dir / "scripts" / "desktop_entry.py")],
    pathex=[str(src_dir)],
    binaries=[],
    datas=[(str(project_dir / "frontend" / "dist"), "frontend/dist")],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest", "IPython", "jupyter", "notebook",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "webview.platforms.qt", "webview.platforms.gtk",
        "webview.platforms.cocoa", "webview.platforms.cef",
        # These are optional packages present in some scientific Conda
        # environments, but are neither imported nor declared by this app.
        # Letting PyInstaller discover them makes the build non-reproducible
        # and can load conflicting OpenMP runtimes (notably via torch).
        "torch", "torchvision", "torchaudio", "tensorflow", "jax", "jaxlib",
        "dask", "distributed", "pyarrow", "sphinx", "docutils",
        "h5py", "botocore", "boto3",
        "pandas", "sklearn", "numba", "llvmlite",
        "openpyxl", "tables", "lxml", "qtpy",
        "panel", "bokeh", "narwhals", "xyzservices", "pyviz_comms",
        "plotly", "seaborn",
        # More environment-only optional integrations. LangGraph's StateGraph
        # needs langchain_core, but this app does not use the high-level
        # langchain package, provider wrappers, tracing, hubs, MCP, notebooks,
        # or alternate database drivers.
        "langchain", "langchain_openai", "langchain_anthropic",
        "langchain_google_genai", "huggingface_hub", "fsspec", "lz4",
        "sentry_sdk", "opentelemetry", "grpc", "mcp", "sympy",
        "psycopg2", "alembic", "mako", "mypy", "twisted",
        "zmq", "ipykernel", "ipywidgets", "traitlets", "tornado",
        "tkinter", "_tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ResearchAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

app = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ResearchAgent",
)
