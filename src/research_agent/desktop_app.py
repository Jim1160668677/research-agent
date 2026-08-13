"""Native desktop runtime for Research Agent.

The desktop build deliberately keeps one process boundary:

1. configure the per-user data and security environment;
2. start FastAPI/Uvicorn on a loopback socket in a managed thread;
3. host the bundled Vue application in a native pywebview window;
4. stop the API, tray, and window deterministically on exit.

Keeping Uvicorn in-process is important for frozen applications.  A PyInstaller
executable is not a Python interpreter, so spawning ``sys.executable -m
uvicorn`` recursively starts the desktop executable instead of a backend.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import socket
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Optional

from loguru import logger


DESKTOP_CONFIG = {
    "app_name": "Research Agent",
    "app_title": "科研智能体系统",
    "window_width": 1280,
    "window_height": 800,
    "window_min_width": 960,
    "window_min_height": 640,
    "api_port": 0,
    "health_check_interval": 0.2,
    "health_check_timeout": 30,
    "theme_color": "#2563eb",
    "debug": False,
    "window_state_debounce_ms": 500,
}


def get_bundle_dir() -> Path:
    """Return the directory containing bundled read-only application assets."""
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            return Path(bundle)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def get_app_dir() -> Path:
    """Backward-compatible alias for the application resource directory."""
    return get_bundle_dir()


def get_user_data_dir() -> Path:
    """Return the writable, per-user application directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home()))
        user_dir = Path(base) / "ResearchAgent"
    elif sys.platform == "darwin":
        user_dir = Path.home() / "Library" / "Application Support" / "ResearchAgent"
    else:
        user_dir = Path.home() / ".local" / "share" / "research-agent"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def get_frontend_dist_dir() -> Path:
    """Locate the built Vue application in development and frozen builds."""
    candidates = (
        get_bundle_dir() / "frontend" / "dist",
        Path(__file__).resolve().parent.parent.parent / "frontend" / "dist",
    )
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return candidates[0]


def get_state_file() -> Path:
    return get_user_data_dir() / "window_state.json"


def _atomic_write_text(path: Path, content: str) -> None:
    """Write a small state file atomically to avoid partial JSON on a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def load_window_state() -> dict[str, Any]:
    state_file = get_state_file()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        width = data.get("width")
        height = data.get("height")
        if width is not None and (not isinstance(width, int) or width < 640):
            data.pop("width", None)
        if height is not None and (not isinstance(height, int) or height < 480):
            data.pop("height", None)
        return data
    except (OSError, ValueError, TypeError):
        return {}


def save_window_state(state: dict[str, Any]) -> None:
    try:
        _atomic_write_text(get_state_file(), json.dumps(state, ensure_ascii=False, indent=2))
    except OSError as exc:
        logger.debug(f"保存窗口状态失败: {exc}")


def _load_or_create_secret(path: Path) -> str:
    """Return a stable installation secret used for JWT and local key encryption."""
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 48:
            return existing
    except OSError:
        pass

    value = secrets.token_urlsafe(64)
    _atomic_write_text(path, value)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows ACLs are inherited from the private AppData directory.
        pass
    return value


def configure_runtime_environment(user_data_dir: Optional[Path] = None) -> dict[str, str]:
    """Configure all environment-backed services before importing the API.

    The function is idempotent and intentionally called before any module that
    constructs SQLAlchemy engines or Pydantic settings is imported.
    """
    data_dir = user_data_dir or get_user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = (data_dir / "research_agent.db").resolve()
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    jwt_secret = _load_or_create_secret(data_dir / ".runtime_secret")

    os.environ["DATABASE_URL"] = database_url
    os.environ["JWT_SECRET"] = jwt_secret
    os.environ["RESEARCH_AGENT_DATA_DIR"] = str(data_dir.resolve())
    os.environ["RESEARCH_AGENT_DESKTOP"] = "1"
    debug_value = "true" if DESKTOP_CONFIG.get("debug", False) else "false"
    os.environ["DEBUG"] = debug_value
    os.environ["RESEARCH_AGENT_DEBUG"] = debug_value
    return {"database_url": database_url, "jwt_secret": jwt_secret}


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"research_agent_{time.strftime('%Y%m%d')}.log"
    logger.remove()
    if not getattr(sys, "frozen", False):
        logger.add(
            sys.stderr,
            level="INFO",
            format=(
                "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
                "<level>{message}</level>"
            ),
        )
    logger.add(
        str(log_file),
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
    )


class SingleInstanceLock:
    """Atomic PID lock with discovery metadata for the already-running instance."""

    def __init__(self, app_name: str = "ResearchAgent"):
        self.lock_file = get_user_data_dir() / f"{app_name}.lock"
        self.locked = False

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            if sys.platform == "win32":
                import ctypes

                query_limited_information = 0x1000
                handle = ctypes.windll.kernel32.OpenProcess(
                    query_limited_information, False, pid
                )
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False

    def _read_record(self) -> dict[str, Any]:
        try:
            raw = self.lock_file.read_text(encoding="utf-8").strip()
            if raw.isdigit():  # compatibility with the previous PID-only format
                return {"pid": int(raw)}
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    @classmethod
    def _record_is_live(cls, record: dict[str, Any]) -> bool:
        """Reject reused/stale PIDs without breaking a legitimate cold start."""
        if not cls._is_pid_alive(int(record.get("pid") or 0)):
            return False
        port = record.get("port")
        if isinstance(port, int) and 0 < port < 65536:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=0.75
                ) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and data.get("status") == "healthy":
                        return True
            except (OSError, ValueError, urllib.error.URLError):
                pass
        try:
            age = time.time() - float(record.get("started_at"))
        except (TypeError, ValueError):
            # A legacy PID-only lock cannot prove identity after PID reuse.
            return False
        return -5 <= age <= DESKTOP_CONFIG["health_check_timeout"] + 5

    def acquire(self) -> bool:
        record = {"pid": os.getpid(), "port": None, "started_at": time.time()}
        payload = json.dumps(record)
        for _ in range(2):
            try:
                descriptor = os.open(
                    self.lock_file,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    stat.S_IRUSR | stat.S_IWUSR,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                self.locked = True
                return True
            except FileExistsError:
                current = self._read_record()
                if self._record_is_live(current):
                    return False
                try:
                    self.lock_file.unlink()
                except OSError:
                    return False
            except OSError as exc:
                logger.error(f"无法创建单实例锁: {exc}")
                return False
        return False

    def update_port(self, port: int) -> None:
        if not self.locked:
            return
        record = self._read_record()
        if record.get("pid") != os.getpid():
            return
        record["port"] = int(port)
        try:
            _atomic_write_text(self.lock_file, json.dumps(record))
        except OSError as exc:
            logger.debug(f"更新实例端口失败: {exc}")

    def running_port(self) -> Optional[int]:
        record = self._read_record()
        if self._record_is_live(record):
            port = record.get("port")
            return int(port) if isinstance(port, int) and port > 0 else None
        return None

    def release(self) -> None:
        if self.locked:
            record = self._read_record()
            if record.get("pid") == os.getpid():
                try:
                    self.lock_file.unlink()
                except OSError:
                    pass
        self.locked = False


class BackendManager:
    """Own an embedded Uvicorn server and its loopback listening socket."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("桌面 API 只能绑定到回环地址")
        self.host = host
        self.port = port
        self.base_url: Optional[str] = None
        self.process = None  # legacy attribute; embedded runtime has no child process
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._socket: Optional[socket.socket] = None
        self._failure: Optional[BaseException] = None

    def _create_socket(self) -> socket.socket:
        family = socket.AF_INET6 if self.host == "::1" else socket.AF_INET
        listener = socket.socket(family, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(2048)
        self.port = int(listener.getsockname()[1])
        return listener

    def start(self) -> bool:
        if self.is_running:
            return True

        import uvicorn
        from .core.app import create_app

        self._failure = None
        self._socket = self._create_socket()
        self.base_url = f"http://{self.host}:{self.port}"
        config = uvicorn.Config(
            create_app(),
            host=self.host,
            port=self.port,
            log_level="debug" if DESKTOP_CONFIG["debug"] else "warning",
            access_log=False,
            log_config=None,
            lifespan="on",
        )
        self._server = uvicorn.Server(config)

        def serve() -> None:
            try:
                self._server.run(sockets=[self._socket])
            except BaseException as exc:  # retained for diagnostics in the UI/log
                self._failure = exc
                logger.exception(f"嵌入式 API 异常退出: {exc}")
            finally:
                try:
                    if self._socket:
                        self._socket.close()
                except OSError:
                    pass

        self._thread = threading.Thread(
            target=serve,
            name="research-agent-api",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"正在启动嵌入式 API: {self.base_url}")

        if self._wait_for_healthy():
            logger.info(f"嵌入式 API 已就绪: {self.base_url}")
            return True

        reason = f": {self._failure}" if self._failure else ""
        logger.error(f"嵌入式 API 启动失败{reason}")
        self.stop()
        return False

    def _wait_for_healthy(self) -> bool:
        deadline = time.monotonic() + DESKTOP_CONFIG["health_check_timeout"]
        url = f"{self.base_url}/health"
        while time.monotonic() < deadline:
            if self._failure or (self._thread and not self._thread.is_alive()):
                return False
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and data.get("status") == "healthy":
                        return True
            except (OSError, ValueError, urllib.error.URLError):
                pass
            time.sleep(DESKTOP_CONFIG["health_check_interval"])
        return False

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        if server is not None:
            server.should_exit = True
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=8)
        if thread and thread.is_alive():
            logger.warning("嵌入式 API 未在超时内停止")
            if server is not None:
                server.force_exit = True
        self._thread = None
        self._server = None
        self._socket = None
        self.base_url = None

    @property
    def is_running(self) -> bool:
        return bool(
            self._thread
            and self._thread.is_alive()
            and self._server is not None
            and not self._server.should_exit
        )


class DesktopApp:
    """Coordinate the native window, embedded API, tray, and durable state."""

    def __init__(self, enable_tray: bool = True, single_instance: bool = True):
        self.user_data_dir = get_user_data_dir()
        from .desktop_config import DesktopConfig

        self.config = DesktopConfig(config_dir=self.user_data_dir)
        window_config = self.config.window
        server_config = self.config.server
        DESKTOP_CONFIG.update({
            "app_title": self.config.app_title,
            "window_width": window_config.get("width", 1280),
            "window_height": window_config.get("height", 800),
            "window_min_width": window_config.get("min_width", 960),
            "window_min_height": window_config.get("min_height", 640),
            "api_port": server_config.get("port", 0),
            "health_check_interval": server_config.get("health_check_interval", 0.2),
            "health_check_timeout": server_config.get("health_check_timeout", 30),
            "theme_color": self.config.theme.get("primary_color", "#2563eb"),
            "debug": bool(server_config.get("debug", False)),
        })
        setup_logging(self.user_data_dir / "logs")
        configure_runtime_environment(self.user_data_dir)

        self.app_dir = get_app_dir()
        self.frontend_dir = get_frontend_dist_dir()
        self.enable_tray = enable_tray and bool(self.config.system.get("tray_enabled", True))
        self.single_instance = single_instance and bool(self.config.system.get("single_instance", True))
        backend_host = server_config.get("host", "127.0.0.1")
        if backend_host not in {"127.0.0.1", "localhost", "::1"}:
            logger.warning(f"已忽略不安全的桌面 API 绑定地址: {backend_host}")
            backend_host = "127.0.0.1"
        self.backend = BackendManager(
            host=backend_host,
            port=DESKTOP_CONFIG["api_port"],
        )
        self.window = None
        self.tray = None
        self.auth = None  # authentication is owned by the Vue session
        self._lock = SingleInstanceLock() if self.single_instance else None
        self._window_state = load_window_state()
        self._window_state_timer: Optional[threading.Timer] = None
        self._window_state_lock = threading.Lock()
        self._pending_state: Optional[dict[str, Any]] = None
        self._window_create_retries = 0  # compatibility with the former runtime
        self._shutdown_started = False
        self._setup_signal_handlers()

        logger.info(f"应用资源目录: {self.app_dir}")
        logger.info(f"用户数据目录: {self.user_data_dir}")
        logger.info(f"前端资源目录: {self.frontend_dir}")

    def _setup_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for signal_name in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(signal_name, self._signal_handler)
            except (OSError, ValueError):
                pass

    def _signal_handler(self, signum, _frame) -> None:
        logger.info(f"收到退出信号: {signum}")
        self.shutdown()

    def initialize_database(self) -> bool:
        """Initialize the configured user database (also done by API lifespan)."""
        try:
            from .core.db import init_db

            asyncio.run(init_db())
            return True
        except Exception as exc:
            logger.exception(f"数据库初始化失败: {exc}")
            return False

    def create_window(self) -> bool:
        try:
            import webview

            state = self._window_state
            kwargs = {
                "title": DESKTOP_CONFIG["app_title"],
                "url": self.backend.base_url,
                "width": state.get("width", DESKTOP_CONFIG["window_width"]),
                "height": state.get("height", DESKTOP_CONFIG["window_height"]),
                "min_size": (
                    DESKTOP_CONFIG["window_min_width"],
                    DESKTOP_CONFIG["window_min_height"],
                ),
                "resizable": True,
                "text_select": True,
                "background_color": "#f8fafc",
                "on_top": bool(state.get("always_on_top", False)),
            }
            if isinstance(state.get("x"), int) and isinstance(state.get("y"), int):
                kwargs.update(x=state["x"], y=state["y"])
            self.window = webview.create_window(**kwargs)
            for event_name, handler in (
                ("closed", self._on_window_closed),
                ("resized", self._on_window_resized),
                ("moved", self._on_window_moved),
                ("minimized", self._on_window_minimized),
            ):
                try:
                    getattr(self.window.events, event_name).__iadd__(handler)
                except Exception:
                    pass
            return True
        except Exception as exc:
            logger.exception(f"无法创建原生窗口: {exc}")
            self.window = None
            return False

    def _snapshot_window_state(self) -> Optional[dict[str, Any]]:
        if self.window is None:
            return None
        try:
            return {
                "width": int(getattr(self.window, "width", DESKTOP_CONFIG["window_width"])),
                "height": int(getattr(self.window, "height", DESKTOP_CONFIG["window_height"])),
                "x": getattr(self.window, "x", None),
                "y": getattr(self.window, "y", None),
            }
        except (TypeError, ValueError):
            return None

    def _on_window_closed(self, _window=None) -> None:
        self._save_current_window_state()

    def _on_window_resized(self, _window=None) -> None:
        self._debounced_save_state()

    def _on_window_moved(self, _window=None) -> None:
        self._debounced_save_state()

    def _on_window_minimized(self, _window=None) -> None:
        if (
            self.config.system.get("minimize_to_tray", True)
            and self.tray
            and self.tray.is_running
            and self.window
        ):
            try:
                self.window.hide()
            except Exception as exc:
                logger.debug(f"最小化到托盘失败: {exc}")

    def _debounced_save_state(self) -> None:
        with self._window_state_lock:
            snapshot = self._snapshot_window_state()
            if snapshot:
                self._pending_state = snapshot
            if self._window_state_timer:
                self._window_state_timer.cancel()
            self._window_state_timer = threading.Timer(
                DESKTOP_CONFIG["window_state_debounce_ms"] / 1000,
                self._flush_pending_state,
            )
            self._window_state_timer.daemon = True
            self._window_state_timer.start()

    def _flush_pending_state(self) -> None:
        with self._window_state_lock:
            state = self._pending_state
            self._pending_state = None
            self._window_state_timer = None
        if state:
            self._window_state = state
            save_window_state(state)

    def _save_current_window_state(self) -> None:
        snapshot = self._snapshot_window_state()
        if snapshot:
            self._window_state = snapshot
            save_window_state(snapshot)
            return
        if self._pending_state:
            self._flush_pending_state()

    def _open_browser_fallback(self, url: Optional[str] = None) -> None:
        target = url or self.backend.base_url or "http://127.0.0.1:8010"
        logger.warning(f"使用系统浏览器打开: {target}")
        webbrowser.open(target)

    def _start_tray(self) -> None:
        if not self.enable_tray or not self.window:
            return
        try:
            from .tray import TrayManager

            self.tray = TrayManager(app=self, window=self.window)
            self.tray.start()
        except Exception as exc:
            logger.warning(f"系统托盘不可用: {exc}")
            self.tray = None

    def _find_existing_port(self) -> Optional[int]:
        if self._lock:
            return self._lock.running_port()
        return None

    def run(self) -> bool:
        if self._lock and not self._lock.acquire():
            port = self._lock.running_port()
            if port:
                self._open_browser_fallback(f"http://127.0.0.1:{port}")
            logger.warning("Research Agent 已在运行")
            return False

        try:
            if not self.frontend_dir.is_dir():
                raise RuntimeError(
                    "前端资源不存在。开发环境请先运行 frontend 的构建命令。"
                )
            if not self.backend.start():
                raise RuntimeError("本地 API 启动失败，请查看日志获取详细原因")
            if self._lock:
                self._lock.update_port(self.backend.port)

            window_created = self.create_window()
            if not window_created:
                self._open_browser_fallback()
                while self.backend.is_running:
                    time.sleep(0.25)
                return True

            self._start_tray()
            if self.tray:
                self.tray.notify("Research Agent", "科研工作台已就绪")

            import webview

            storage_path = self.user_data_dir / "webview"
            storage_path.mkdir(parents=True, exist_ok=True)
            webview.start(
                debug=DESKTOP_CONFIG["debug"],
                private_mode=False,
                storage_path=str(storage_path),
            )
            return True
        except Exception as exc:
            logger.exception(f"桌面应用启动失败: {exc}")
            return False
        finally:
            self.shutdown()

    def exit(self) -> None:
        self.shutdown()
        if threading.current_thread() is threading.main_thread():
            raise SystemExit(0)

    def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        logger.info("正在关闭 Research Agent")
        self._save_current_window_state()
        if self._window_state_timer:
            self._window_state_timer.cancel()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
            self.tray = None
        self.backend.stop()
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None
        if self._lock:
            self._lock.release()
        logger.info("Research Agent 已安全退出")


def main() -> int:
    app = DesktopApp()
    return 0 if app.run() else 1


if __name__ == "__main__":
    raise SystemExit(main())
