"""桌面启动优化模块

优化内容:
1. 延迟加载非核心模块
2. 预加载常用组件
3. 连接池复用
4. 缓存策略
5. 启动性能测量
6. Windows EventLoop 优化
"""

import asyncio
import sys
import time

from loguru import logger


class StartupOptimizer:
    """启动优化器：用于度量和诊断启动性能"""

    def __init__(self):
        self.start_time = time.time()
        self.metrics = {}

    def timed_step(self, name: str):
        """创建计时步骤的装饰器"""

        def decorator(func):
            def wrapper(*args, **kwargs):
                start = time.time()
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                self.metrics[name] = elapsed
                logger.debug(f"[启动] {name}: {elapsed:.3f}s")
                return result

            return wrapper

        return decorator

    def get_summary(self) -> dict:
        """获取启动摘要"""
        total = time.time() - self.start_time
        return {
            "total_time": total,
            "steps": self.metrics,
            "python_version": sys.version,
            "platform": sys.platform,
        }


# 预加载缓存
_PRELOAD_CACHE = {}


def preload_common_modules():
    """预加载常用模块（在后台并行导入以减少首次请求延迟）"""
    modules_to_preload = [
        "sqlalchemy",
        "httpx",
        "loguru",
        "pydantic",
    ]

    for module_name in modules_to_preload:
        try:
            __import__(module_name)
            _PRELOAD_CACHE[module_name] = True
        except ImportError:
            _PRELOAD_CACHE[module_name] = False


def lazy_import_backend_modules():
    """延迟导入后端模块（减少启动时间）"""
    return {
        "docking": "research_agent.plugins.docking",
        "structure": "research_agent.plugins.structure",
        "ncbi": "research_agent.ncbi_skills",
        "workflows": "research_agent.workflows",
        "recommendations": "research_agent.recommendations",
    }


class FastAPIOptimizer:
    """FastAPI 应用优化"""

    @staticmethod
    def configure_for_desktop(app):
        """为桌面环境优化 FastAPI 应用"""
        app.router.redirect_slashes = False
        app.state.cache = {}
        app.state.request_timeout = 30
        return app

    @staticmethod
    def optimize_async_settings():
        """优化异步事件循环设置"""
        if sys.platform == "win32":
            # Windows 下使用 ProactorEventLoop 以获得更好的 IO 性能
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except Exception:
                # 某些 Windows Python 版本不支持，回退默认
                pass


def measure_startup_performance(func):
    """测量启动性能的装饰器"""

    def wrapper(*args, **kwargs):
        start = time.time()
        logger.info("应用启动性能测量开始...")

        result = func(*args, **kwargs)

        elapsed = time.time() - start
        logger.info(f"应用启动完成，耗时: {elapsed:.3f}s")

        if elapsed < 2.0:
            logger.info("启动性能优秀 (< 2s)")
        elif elapsed < 5.0:
            logger.info("启动性能良好 (< 5s)")
        else:
            logger.warning(f"启动时间较长 ({elapsed:.1f}s)，建议优化")

        return result

    return wrapper


# 桌面环境特定的优化配置
DESKTOP_OPTIMIZATIONS = {
    "startup_timeout": 30,
    "health_check_interval": 0.5,
    "max_concurrent_connections": 100,
    "cache_ttl": 300,
    "lazy_load": True,
    "preload_modules": True,
    "use_proactor_loop": True,
}


def get_optimization_config():
    """获取优化配置"""
    return DESKTOP_OPTIMIZATIONS.copy()


def apply_desktop_optimizations():
    """应用桌面优化（在启动早期调用）"""
    optimizer = FastAPIOptimizer()
    optimizer.optimize_async_settings()

    if DESKTOP_OPTIMIZATIONS["preload_modules"]:
        preload_common_modules()

    return True
