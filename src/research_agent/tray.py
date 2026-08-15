"""系统托盘模块

提供桌面应用系统托盘功能，包括：
- 显示/隐藏主窗口
- 快速操作菜单
- 状态通知
- 启动/关闭操作
"""

import threading

from loguru import logger


class TrayManager:
    """系统托盘管理器"""

    def __init__(self, app=None, window=None):
        self.app = app
        self.window = window
        self.tray_icon = None
        self._running = False
        self._thread = None

    def start(self):
        """启动系统托盘（异步）"""
        if self._running:
            return

        try:
            self._init_tray()
            self._running = True
            self._thread = threading.Thread(target=self._run_tray, daemon=True)
            self._thread.start()
            logger.info("系统托盘已启动")
        except Exception as e:
            logger.warning(f"系统托盘启动失败: {e}")

    def _init_tray(self):
        """初始化托盘图标和菜单"""
        try:
            import pystray

            image = self._create_icon_image()
            menu = self._create_menu()

            self.tray_icon = pystray.Icon(
                "ResearchAgent",
                image,
                "科研智能体系统",
                menu,
            )
        except ImportError:
            logger.warning("pystray 或 pillow 未安装，托盘功能不可用")
            raise

    def _create_icon_image(self):
        """创建托盘图标 (RA 风格)"""
        try:
            from PIL import Image, ImageDraw, ImageFont

            image = Image.new('RGBA', (64, 64), (24, 144, 255, 255))
            draw = ImageDraw.Draw(image)

            # 绘制圆角矩形背景
            draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill=(37, 99, 235, 255))

            # 绘制 "RA" 文字
            try:
                font = ImageFont.truetype("arial.ttf", 28)
            except OSError:
                font = ImageFont.load_default()

            draw.text((16, 10), "RA", fill="white", font=font)

            return image
        except ImportError:
            return self._create_simple_png()

    def _create_simple_png(self):
        """不依赖 PIL 的简化图标"""
        import struct
        import zlib

        def chunk(chunk_type, data):
            c = chunk_type + data
            crc = struct.pack('>I', zlib.crc32(c) & 0xffffffff)
            return struct.pack('>I', len(data)) + c + crc

        width, height = 64, 64
        color = (37, 99, 235)

        header = b'\x89PNG\r\n\x1a\n'
        ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))

        raw = b''
        for _y in range(height):
            raw += b'\x00'
            for _x in range(width):
                raw += bytes(color)

        idat = chunk(b'IDAT', zlib.compress(raw))
        iend = chunk(b'IEND', b'')
        return header + ihdr + idat + iend

    def _create_menu(self):
        """创建托盘菜单"""
        try:
            import pystray

            items = []

            # 主操作：显示/隐藏窗口
            if self.window:
                items.append(
                    pystray.MenuItem(
                        "显示主窗口",
                        self._show_window,
                        default=True,
                    )
                )
                items.append(
                    pystray.MenuItem(
                        "隐藏到托盘",
                        self._hide_window,
                    )
                )
                items.append(pystray.Menu.SEPARATOR)

            # 导航快捷方式
            items.append(
                pystray.MenuItem("🔌 插件市场", self._open_plugins)
            )
            items.append(
                pystray.MenuItem("⚙️ 工作流", self._open_workflows)
            )
            items.append(
                pystray.MenuItem("💬 智能对话", self._open_chat)
            )
            items.append(pystray.Menu.SEPARATOR)

            # 设置
            items.append(
                pystray.MenuItem("设置", self._open_settings)
            )
            items.append(pystray.Menu.SEPARATOR)

            # 退出
            items.append(
                pystray.MenuItem(
                    "退出 Research Agent",
                    self._quit,
                )
            )

            return pystray.Menu(*items)
        except Exception:
            return None

    def _run_tray(self):
        """运行托盘主循环"""
        if self.tray_icon:
            try:
                self.tray_icon.run()
            except Exception as e:
                logger.error(f"托盘运行异常: {e}")
            finally:
                self._running = False

    def stop(self):
        """停止系统托盘"""
        self._running = False
        icon = self.tray_icon
        thread = self._thread
        if icon:
            try:
                icon.stop()
            except Exception:
                pass
        if thread and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=2)
        self.tray_icon = None
        self._thread = None
        logger.info("系统托盘已停止")

    # ---- 窗口操作 ----

    def _show_window(self, icon=None, item=None):
        """显示窗口"""
        if self.window:
            try:
                self.window.show()
                self.window.restore()
                # 置顶并聚焦
                try:
                    self.window.on_top = True
                    self.window.on_top = False
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"显示窗口失败: {e}")

    def _hide_window(self, icon=None, item=None):
        """隐藏窗口到托盘"""
        if self.window:
            try:
                self.window.hide()
                if self.tray_icon:
                    self.tray_icon.notify("已最小化到托盘", "点击托盘图标显示窗口")
            except Exception as e:
                logger.error(f"隐藏窗口失败: {e}")

    def _toggle_window(self, icon=None, item=None):
        """切换窗口显示"""
        if self.window:
            try:
                if self.window.visible:
                    self.window.hide()
                else:
                    self.window.show()
                    self.window.restore()
            except Exception as e:
                logger.error(f"切换窗口失败: {e}")

    # ---- 导航操作 ----

    def _open_plugins(self, icon=None, item=None):
        """导航到插件市场"""
        self._navigate_to("/plugins")

    def _open_workflows(self, icon=None, item=None):
        """导航到工作流"""
        self._navigate_to("/workflows")

    def _open_chat(self, icon=None, item=None):
        """导航到智能对话"""
        self._navigate_to("/chat")

    def _open_settings(self, icon=None, item=None):
        """打开设置"""
        self._navigate_to("/llm")

    def _navigate_to(self, path):
        """导航到指定路径"""
        if self.window:
            try:
                # 确保窗口可见
                if not self.window.visible:
                    self.window.show()
                    self.window.restore()
                self.window.evaluate_js(f'window.location.href = "{path}"')
            except Exception as e:
                logger.error(f"导航失败: {e}")

    def _quit(self, icon=None, item=None):
        """退出应用"""
        if self.app:
            self.app.exit()
        else:
            import sys
            sys.exit(0)

    def notify(self, title: str, message: str):
        """显示系统通知"""
        try:
            if self.tray_icon:
                self.tray_icon.notify(message, title)
        except Exception as e:
            logger.error(f"通知发送失败: {e}")

    @property
    def is_running(self) -> bool:
        """托盘是否在运行"""
        return self._running


def create_tray(app=None, window=None) -> TrayManager:
    """创建托盘管理器"""
    return TrayManager(app, window)
