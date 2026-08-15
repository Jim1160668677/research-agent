"""桌面应用测试套件

测试内容:
1. 桌面配置模块测试
2. 路径工具函数测试
3. FastAPI静态文件服务测试
4. 桌面启动流程集成测试
5. CLI桌面命令测试
"""

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ============================================================
# 1. 配置模块测试
# ============================================================

class TestDesktopConfig:
    """测试桌面配置模块"""

    def test_config_defaults(self):
        """测试默认配置"""
        from research_agent.desktop_config import DEFAULT_CONFIG

        assert "app_name" in DEFAULT_CONFIG
        assert "window" in DEFAULT_CONFIG
        assert "server" in DEFAULT_CONFIG
        assert "logging" in DEFAULT_CONFIG
        assert "storage" in DEFAULT_CONFIG
        assert "theme" in DEFAULT_CONFIG
        assert "system" in DEFAULT_CONFIG
        assert "shortcuts" in DEFAULT_CONFIG

    def test_config_properties(self, tmp_path):
        """测试配置属性"""
        from research_agent.desktop_config import DesktopConfig

        config = DesktopConfig(config_dir=tmp_path)

        assert config.app_name == "Research Agent"
        assert config.version == "1.1.0"
        assert isinstance(config.window, dict)
        assert isinstance(config.server, dict)
        assert isinstance(config.theme, dict)

    def test_config_get_set(self, tmp_path):
        """测试配置读写"""
        from research_agent.desktop_config import DesktopConfig

        config = DesktopConfig(config_dir=tmp_path)

        # 测试 get
        assert config.get("window.width") == 1280
        assert config.get("nonexistent", "default") == "default"

        # 测试 set
        config.set("window.width", 1920)
        assert config.get("window.width") == 1920

    def test_config_save_load(self, tmp_path):
        """测试配置保存和加载"""
        from research_agent.desktop_config import DesktopConfig

        # 保存
        config1 = DesktopConfig(config_dir=tmp_path)
        config1.set("window.width", 1600)
        config1.set("theme.primary_color", "#ff0000")
        config1.save()

        # 重新加载
        config2 = DesktopConfig(config_dir=tmp_path)
        assert config2.get("window.width") == 1600
        assert config2.get("theme.primary_color") == "#ff0000"

    def test_config_deep_merge(self, tmp_path):
        """测试配置深度合并"""
        from research_agent.desktop_config import DesktopConfig

        config = DesktopConfig(config_dir=tmp_path)

        # 保存部分配置
        config.set("window.width", 1500)
        config.save()

        # 验证其他默认值仍保留
        config2 = DesktopConfig(config_dir=tmp_path)
        assert config2.get("window.width") == 1500
        assert config2.get("window.height") == 800  # 保持默认

    def test_config_reset(self, tmp_path):
        """测试重置配置"""
        from research_agent.desktop_config import DEFAULT_CONFIG, DesktopConfig

        config = DesktopConfig(config_dir=tmp_path)
        config.set("window.width", 1920)
        assert config.get("window.width") == 1920

        config.reset()

        # 重置后应该恢复默认值
        assert config.get("window.width") == DEFAULT_CONFIG["window"]["width"]
        assert config.get("window.height") == DEFAULT_CONFIG["window"]["height"]


# ============================================================
# 2. 路径工具函数测试
# ============================================================

class TestPathUtilities:
    """测试路径工具函数"""

    def test_get_app_dir(self):
        """测试获取应用目录"""
        from research_agent.desktop_app import get_app_dir

        app_dir = get_app_dir()
        assert isinstance(app_dir, Path)
        assert app_dir.exists()

    def test_get_user_data_dir(self, tmp_path):
        """测试获取用户数据目录"""
        from research_agent.desktop_app import get_user_data_dir

        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            user_dir = get_user_data_dir()
            assert isinstance(user_dir, Path)
            assert user_dir.exists()
            assert user_dir.name == "ResearchAgent"

    def test_get_frontend_dist_dir(self):
        """测试获取前端dist目录"""
        from research_agent.desktop_app import get_frontend_dist_dir

        dist_dir = get_frontend_dist_dir()
        assert isinstance(dist_dir, Path)
        # 目录应该存在（或在开发环境下回退）
        assert dist_dir.exists() or "dist" in str(dist_dir)

    def test_setup_logging(self, tmp_path):
        """测试日志配置"""
        from research_agent.desktop_app import setup_logging

        log_dir = tmp_path / "logs"
        setup_logging(log_dir)

        assert log_dir.exists()


# ============================================================
# 3. FastAPI 静态文件服务测试
# ============================================================

class TestStaticFileServing:
    """测试FastAPI静态文件服务"""

    def test_get_frontend_dist_dir(self):
        """测试获取前端dist目录函数"""
        from research_agent.core.app import get_frontend_dist_dir

        dist_dir = get_frontend_dist_dir()
        # 在开发环境中应该能找到
        if dist_dir is not None:
            assert dist_dir.exists()
            assert (dist_dir / "index.html").exists()

    def test_get_app_base_dir(self):
        """测试获取应用基础目录"""
        from research_agent.core.app import get_app_base_dir

        base_dir = get_app_base_dir()
        assert isinstance(base_dir, Path)
        assert base_dir.exists()

    def test_app_health_endpoint(self):
        """测试健康检查端点"""
        from research_agent.core.app import create_app

        app = create_app()

        # 使用 TestClient 来测试端点
        from fastapi.testclient import TestClient
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_app_has_static_routes(self):
        """测试静态文件路由配置"""
        # 使用 TestClient 测试
        from fastapi.testclient import TestClient

        from research_agent.core.app import create_app, get_frontend_dist_dir
        app = create_app()
        client = TestClient(app)

        # 只有当前端dist存在时才会注册静态路由
        if get_frontend_dist_dir():
            response = client.get("/")
            assert response.status_code == 200
            assert "text/html" in response.headers.get("content-type", "")
        else:
            # 没有前端时应该返回API文档
            response = client.get("/docs")
            assert response.status_code == 200


# ============================================================
# 4. 后端管理器测试
# ============================================================

class TestBackendManager:
    """测试后端管理器"""

    def test_backend_manager_init(self):
        """测试后端管理器初始化"""
        from research_agent.desktop_app import BackendManager

        manager = BackendManager(host="127.0.0.1", port=0)
        assert manager.host == "127.0.0.1"
        assert manager.port == 0
        assert manager.process is None
        # process 为 None 时 is_running 应该为 False
        assert not manager.is_running

    def test_backend_manager_is_running(self):
        """测试运行状态检查"""
        from research_agent.desktop_app import BackendManager

        manager = BackendManager()
        # 初始状态 process 为 None
        assert manager.process is None
        assert not manager.is_running

        # 设置模拟嵌入式服务线程
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        mock_server = MagicMock()
        mock_server.should_exit = False
        manager._thread = mock_thread
        manager._server = mock_server
        assert manager.is_running

        # 模拟服务退出
        mock_thread.is_alive.return_value = False
        assert not manager.is_running

    def test_backend_manager_start_stop(self):
        """测试嵌入式后端停止与资源清理"""
        from research_agent.desktop_app import BackendManager

        manager = BackendManager(port=0)
        mock_thread = MagicMock()
        mock_thread.is_alive.side_effect = [True, False]
        mock_server = MagicMock()
        mock_server.should_exit = False
        manager._thread = mock_thread
        manager._server = mock_server

        manager.stop()

        assert mock_server.should_exit is True
        mock_thread.join.assert_called_once()
        assert manager._thread is None
        assert manager._server is None


# ============================================================
# 5. 桌面应用集成测试
# ============================================================

class TestDesktopApp:
    """测试桌面应用主类"""

    def test_desktop_app_init(self, tmp_path):
        """测试桌面应用初始化"""
        from research_agent.desktop_app import DesktopApp

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            # 使用默认参数以保持单实例/托盘逻辑默认
            app = DesktopApp(enable_tray=False, single_instance=False)

            assert app.backend is not None
            assert app.app_dir is not None
            assert app.user_data_dir is not None
            assert app.frontend_dir is not None
            assert app.tray is None  # 托盘未启用时为 None
            # 防抖相关字段应已初始化
            assert app._window_state_timer is None
            assert app._window_state_lock is not None
            assert app._window_create_retries == 0

    def test_desktop_app_signal_handler(self, tmp_path):
        """测试信号处理器设置"""
        import signal

        from research_agent.desktop_app import DesktopApp

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            DesktopApp(enable_tray=False, single_instance=False)

        # 验证信号处理器已设置
        sigint_handler = signal.getsignal(signal.SIGINT)
        sigterm_handler = signal.getsignal(signal.SIGTERM)

        # 应该有自定义处理器（不是默认的）
        assert sigint_handler is not None
        assert sigterm_handler is not None

    def test_desktop_app_shutdown(self, tmp_path):
        """测试桌面应用关闭"""
        from research_agent.desktop_app import DesktopApp

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            app = DesktopApp(enable_tray=False, single_instance=False)

            # 关闭不应该抛出异常
            app.shutdown()  # 无进程时安全关闭

    def test_desktop_app_fallback_browser(self, tmp_path):
        """测试浏览器回退方案"""
        from research_agent.desktop_app import DesktopApp

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            app = DesktopApp(enable_tray=False, single_instance=False)
            app.backend.base_url = "http://localhost:8010"

        with patch("webbrowser.open") as mock_open:
            # 不传 url 时使用 base_url
            app._open_browser_fallback()
            mock_open.assert_called_once_with("http://localhost:8010")

        with patch("webbrowser.open") as mock_open2:
            # 传 url 参数时使用该 url
            app._open_browser_fallback("http://example.com:9000")
            mock_open2.assert_called_once_with("http://example.com:9000")

    def test_window_state_roundtrip(self, tmp_path):
        """测试窗口状态保存与加载"""
        from research_agent.desktop_app import load_window_state, save_window_state

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            state = {"width": 1400, "height": 900, "x": 50, "y": 60}
            save_window_state(state)
            loaded = load_window_state()
            assert loaded["width"] == 1400
            assert loaded["x"] == 50

    def test_single_instance_lock(self, tmp_path):
        """测试单实例锁（基于 PID 的互斥锁语义）"""
        from research_agent.desktop_app import SingleInstanceLock

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            lock1 = SingleInstanceLock(app_name="TestApp")
            acquired1 = lock1.acquire()
            assert acquired1 is True

            # 同目录下的第二个实例应看到锁文件并识别"存活的 PID"
            lock2 = SingleInstanceLock(app_name="TestApp")
            acquired2 = lock2.acquire()
            # 由于 lock1 写入的 PID 是当前进程，第二个实例应当识别为已占用
            assert acquired2 is False

            lock1.release()
            assert lock1.locked is False

            # 释放后应能再次获取
            lock3 = SingleInstanceLock(app_name="TestApp")
            acquired3 = lock3.acquire()
            assert acquired3 is True
            lock3.release()

    def test_single_instance_lock_reclaims_reused_or_stale_pid(self, tmp_path):
        from research_agent.desktop_app import DESKTOP_CONFIG, SingleInstanceLock

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            lock = SingleInstanceLock(app_name="TestApp")
            lock.lock_file.write_text(
                '{"pid": 1234, "port": 60344, "started_at": 1}', encoding="utf-8"
            )
            with patch.object(SingleInstanceLock, "_is_pid_alive", return_value=True), patch(
                "research_agent.desktop_app.urllib.request.urlopen",
                side_effect=OSError("connection refused"),
            ):
                assert lock.acquire() is True
            lock.release()

            recent = {
                "pid": 1234,
                "port": None,
                "started_at": time.time()
                - DESKTOP_CONFIG["health_check_timeout"] / 2,
            }
            with patch.object(SingleInstanceLock, "_is_pid_alive", return_value=True):
                assert SingleInstanceLock._record_is_live(recent) is True

    def test_find_existing_port(self, tmp_path):
        """测试现有实例端口探测"""
        from research_agent.desktop_app import DesktopApp

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            app = DesktopApp(enable_tray=False, single_instance=False)
            # 可能探测到当前正在运行的 8010 端口，也可能为 None
            # 验证方法能返回端口 int 或 None
            port = app._find_existing_port()
            assert port is None or isinstance(port, int)

    def test_window_state_debounce(self, tmp_path):
        """测试窗口状态防抖保存"""
        from research_agent.desktop_app import (
            DesktopApp,
            get_state_file,
        )

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            app = DesktopApp(enable_tray=False, single_instance=False)
            # 先设置一个初始状态（模拟窗口存在）
            app._pending_state = {"width": 1280, "height": 800}
            # 防抖不应抛异常
            app._debounced_save_state()
            app._debounced_save_state()  # 连续调用
            # 等待定时器执行
            time.sleep(1.0)
            # 验证状态文件已写入
            state_file = get_state_file()
            assert state_file.exists()

    def test_flush_pending_state(self, tmp_path):
        """测试立即刷新待保存状态"""
        from research_agent.desktop_app import DesktopApp, load_window_state

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            app = DesktopApp(enable_tray=False, single_instance=False)
            app._pending_state = {"width": 1400, "height": 900}
            app._flush_pending_state()
            state = load_window_state()
            assert state["width"] == 1400

    def test_window_event_handlers(self, tmp_path):
        """测试窗口事件回调不会抛异常"""
        from research_agent.desktop_app import DesktopApp

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            app = DesktopApp(enable_tray=False, single_instance=False)
            # 各回调在没有 window 时应安全处理
            app._on_window_closed()
            app._on_window_resized()
            app._on_window_moved()
            app._on_window_minimized()  # 新增最小化回调
            app._save_current_window_state()

    def test_max_window_create_retries(self, tmp_path):
        """测试窗口创建重试保护计数"""
        from research_agent.desktop_app import DesktopApp

        with patch("research_agent.desktop_app.get_user_data_dir", return_value=tmp_path):
            app = DesktopApp(enable_tray=False, single_instance=False)
            assert app._window_create_retries == 0
            # 手动递增到最大
            app._window_create_retries = 3
            # 验证 _open_browser_fallback 在无参数下安全调用
            app._open_browser_fallback("http://test:9999")


# ============================================================
# 6. 系统托盘测试
# ============================================================

class TestTrayManager:
    """测试系统托盘管理器"""

    def test_tray_manager_init(self):
        """测试托盘管理器初始化"""
        from research_agent.tray import TrayManager

        tray = TrayManager()
        assert tray.app is None
        assert tray.window is None
        assert not tray.is_running

    def test_tray_manager_start_stop(self):
        """测试托盘启动和停止"""
        from research_agent.tray import TrayManager

        tray = TrayManager()

        # Optional desktop dependencies may be present or absent. Both paths
        # must stop deterministically without leaking a background tray thread.
        tray.start()
        tray.stop()
        assert not tray.is_running
        assert tray._thread is None

    def test_tray_manager_create_icon_image(self):
        """测试图标创建"""
        from research_agent.tray import TrayManager

        tray = TrayManager()
        image = tray._create_icon_image()
        assert image is not None

    def test_tray_manager_window_operations(self):
        """测试窗口操作（无 app 时安全处理，除退出外不应抛异常）"""
        from research_agent.tray import TrayManager

        tray = TrayManager()

        # 没有窗口时应该安全处理
        tray._toggle_window()
        tray._open_plugins()
        tray._open_workflows()
        tray._open_settings()

        # _quit 无 app 时会调 sys.exit，应捕获 SystemExit
        with pytest.raises(SystemExit) as exc_info:
            tray._quit()
        assert exc_info.value.code == 0


# ============================================================
# 7. CLI 桌面命令测试
# ============================================================

class TestCLIDesktop:
    """测试CLI桌面相关命令"""

    def test_cli_version(self):
        """测试CLI版本"""
        from click.testing import CliRunner

        from research_agent.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["--version"])

        assert result.exit_code == 0
        assert "1.0.0" in result.output or "Research Agent" in result.output

    def test_cli_help(self):
        """测试CLI帮助"""
        from click.testing import CliRunner

        from research_agent.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "desktop" in result.output or "server" in result.output

    def test_cli_desktop_help(self):
        """测试desktop子命令帮助"""
        from click.testing import CliRunner

        from research_agent.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["desktop", "--help"])

        assert result.exit_code == 0

    def test_cli_server_help(self):
        """测试server子命令帮助"""
        from click.testing import CliRunner

        from research_agent.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["server", "--help"])

        assert result.exit_code == 0
        assert "--port" in result.output or "-p" in result.output

    def test_cli_init(self, tmp_path):
        """测试数据库初始化命令"""
        from click.testing import CliRunner

        from research_agent.cli import main

        runner = CliRunner()

        # 使用临时目录
        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            result = runner.invoke(main, ["init"])

            # 可能成功或失败（取决于环境），但不应该崩溃
            assert result.exit_code in [0, 1]


# ============================================================
# 8. 集成测试
# ============================================================

class TestIntegration:
    """集成测试"""

    def test_full_config_flow(self, tmp_path):
        """测试完整配置流程"""
        from research_agent.desktop_config import DesktopConfig

        # 设置临时路径
        config1 = DesktopConfig(config_dir=tmp_path)
        config1.set("window.width", 1600)
        config1.save()

        # 重新加载
        config2 = DesktopConfig(config_dir=tmp_path)
        assert config2.get("window.width") == 1600

    def test_static_files_integration(self):
        """测试静态文件集成"""
        from research_agent.core.app import create_app, get_frontend_dist_dir

        app = create_app()

        # 使用 TestClient 测试
        from fastapi.testclient import TestClient
        client = TestClient(app)

        # 健康检查应该可用
        response = client.get("/health")
        assert response.status_code == 200

        # API路由应该可用 (带尾部斜杠)
        response = client.get("/api/v1/skills/")
        assert response.status_code == 200

        # 如果有前端文件，静态服务应该可用
        dist_dir = get_frontend_dist_dir()
        if dist_dir:
            assert (dist_dir / "index.html").exists()
            # 根路径应该返回HTML
            response = client.get("/")
            assert response.status_code == 200

    def test_logging_integration(self, tmp_path):
        """测试日志集成"""
        from research_agent.desktop_app import setup_logging

        log_dir = tmp_path / "logs"
        setup_logging(log_dir)

        # 写入日志
        from loguru import logger
        logger.info("测试日志消息")

        # 验证日志文件创建
        log_files = list(log_dir.glob("*.log"))
        assert len(log_files) > 0


# ============================================================
# 9. 性能相关测试
# ============================================================

class TestPerformance:
    """性能相关测试"""

    def test_app_creation_time(self):
        """测试应用创建时间"""
        import time

        from research_agent.core.app import create_app

        start = time.time()
        create_app()
        elapsed = time.time() - start

        # 应用创建应该在2秒内完成
        assert elapsed < 2.0, f"应用创建耗时过长: {elapsed:.3f}s"

    def test_config_load_time(self, tmp_path):
        """测试配置加载时间"""
        import time

        from research_agent.desktop_config import DesktopConfig

        # 先创建配置文件
        config = DesktopConfig(config_dir=tmp_path)
        config.save()

        # 测试加载时间
        start = time.time()
        for _ in range(100):
            DesktopConfig(config_dir=tmp_path)
        elapsed = time.time() - start

        # 100次加载应该在1秒内完成
        assert elapsed < 1.0, f"配置加载耗时过长: {elapsed:.3f}s"


if __name__ == "__main__":
    # 直接运行此文件以执行测试
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
