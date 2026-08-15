"""Core application setup and configuration"""

import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from pydantic import ValidationError
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""

    # Server
    host: str = "0.0.0.0"
    port: int = 8010
    debug: bool = False
    app_name: str = "Research Agent"
    version: str = "1.3.0"

    # AI Models
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    google_api_key: str = ""
    google_model: str = "gemini-1.5-pro"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    agnes_api_key: str = ""
    agnes_model: str = "agnes-2.0-flash"

    # NCBI
    ncbi_api_key: str = ""
    ncbi_email: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./research_agent.db"

    # Security (default empty — must be set via env or .env in production)
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_hours: int = 24
    refresh_token_expire_days: int = 7

    # CORS (restricted by default — configure for production)
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:8010"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["GET", "POST", "PUT", "DELETE", "PATCH"]
    cors_allow_headers: list[str] = ["Authorization", "Content-Type", "Accept"]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


def validate_security_config():
    """启动时验证安全配置

    检查项:
    1. JWT_SECRET 非空
    2. CORS 白名单合理 (不允许生产环境使用 *)
    3. 必要的安全配置完备
    """
    # 1. JWT 密钥
    if not settings.jwt_secret:
        if settings.debug:
            settings.jwt_secret = secrets.token_urlsafe(48)
            logger.warning(
                "JWT_SECRET 未配置，debug 模式下自动生成临时密钥。"
                "生产环境必须在 .env 中显式设置 JWT_SECRET。"
            )
        else:
            raise RuntimeError(
                "JWT_SECRET 未配置。生产环境必须设置强密钥:\n"
                "  方式1: 环境变量 set JWT_SECRET=<strong-random-key>\n"
                "  方式2: .env 文件添加 JWT_SECRET=<strong-random-key>"
            )

    # 2. CORS 检查: 生产环境禁止使用通配符
    if not settings.debug and "*" in settings.allowed_origins:
        raise RuntimeError(
            "生产环境禁止 CORS 使用 '*' 通配符。\n"
            "请通过 ALLOWED_ORIGINS 环境变量设置具体的前端地址列表。"
        )

    # 3. 日志安全配置摘要
    logger.info(f"安全配置验证通过: debug={settings.debug}, "
                f"cors_origins={settings.allowed_origins}")


# Global settings instance
settings = Settings()


def get_app_base_dir() -> Path:
    """获取应用基础目录（兼容 PyInstaller）"""
    if getattr(sys, 'frozen', False):
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            return Path(bundle)
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent.parent


def get_frontend_dist_dir() -> Path | None:
    """获取前端 dist 目录"""
    base_dir = get_app_base_dir()
    candidates = [
        base_dir / "frontend" / "dist",
        Path(__file__).resolve().parent.parent.parent / "frontend" / "dist",
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "index.html").exists():
            return candidate
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理器"""
    # 启动阶段
    logger.info(f"Starting {settings.app_name} v{settings.version}")
    logger.info(f"Debug mode: {settings.debug}")

    # Database readiness is a hard startup requirement. Uvicorn does not
    # accept requests until the lifespan context has entered successfully.
    from .db import init_db
    await init_db()

    try:
        from ..research.artifacts import ArtifactStore

        purged = ArtifactStore.from_database_url(settings.database_url).purge_materialized()
        if purged:
            logger.warning(f"Purged {purged} stale materialized artifact file(s)")
    except Exception as e:
        logger.warning(f"Artifact plaintext recovery cleanup skipped: {e}")

    try:
        from ..execution import recover_pipeline_runs
        recovered = await recover_pipeline_runs()
        if recovered:
            logger.warning(f"Recovered {recovered} interrupted pipeline run(s)")
    except Exception as e:
        logger.warning(f"Pipeline recovery skipped: {e}")

    try:
        from ..research import recover_research_runs
        recovered = await recover_research_runs()
        if recovered:
            logger.warning(f"Recovered {recovered} interrupted research run(s)")
    except Exception as e:
        logger.warning(f"Research recovery skipped: {e}")

    try:
        from ..plugins import PluginManager
        from ..workflows import WorkflowEngine
        PluginManager.initialize()
        WorkflowEngine.initialize()
        recovered = await WorkflowEngine.recover_interrupted_runs()
        if recovered:
            logger.warning(f"Recovered {recovered} interrupted workflow run(s)")
    except Exception as e:
        logger.warning(f"插件/工作流初始化跳过: {e}")

    # 初始化事件追踪器
    try:
        from pathlib import Path

        from ..analytics import EventTracker, UsageScenarioSimulator, set_simulator, set_tracker
        storage_dir = Path(settings.database_url.replace("sqlite+aiosqlite:///", ""))
        storage_dir = storage_dir.parent if storage_dir.suffix == ".db" else storage_dir
        tracker = EventTracker(storage_dir=storage_dir / "analytics", enabled=True)
        simulator = UsageScenarioSimulator()
        set_tracker(tracker)
        set_simulator(simulator)
        logger.info("事件追踪器已初始化")
    except Exception as e:
        logger.warning(f"事件追踪器初始化跳过: {e}")

    yield

    # 关闭阶段
    logger.info("Shutting down application")
    try:
        from ..analytics import get_tracker
        tracker = get_tracker()
        if tracker:
            tracker.shutdown()
    except Exception:
        pass

    try:
        from ..research import shutdown_run_manager
        await shutdown_run_manager()
    except Exception as e:
        logger.warning(f"科研任务运行时关闭失败: {e}")

    try:
        from ..execution import shutdown_pipeline_manager
        await shutdown_pipeline_manager()
    except Exception as e:
        logger.warning(f"Pipeline runtime shutdown failed: {e}")

    try:
        from .db import close_db
        await close_db()
    except Exception as e:
        logger.warning(f"数据库关闭失败: {e}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""

    # 启动时验证安全配置
    validate_security_config()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="面向科研场景的通用智能体系统",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ---------- 全局异常处理器 ----------

    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError):
        """统一处理 Pydantic 验证错误，返回结构化错误信息"""
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            })
        logger.warning(f"输入验证失败: {request.method} {request.url.path} - {errors}")
        return JSONResponse(
            status_code=422,
            content={
                "detail": "输入数据验证失败",
                "errors": errors,
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """Return the same stable envelope for FastAPI request validation."""
        errors = [
            {
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": "输入数据验证失败",
                "errors": errors,
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """统一处理 HTTP 异常"""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "request_id": getattr(request.state, "request_id", None),
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局异常处理器，防止敏感信息泄露"""
        request_id = getattr(request.state, "request_id", None)
        logger.error(f"未处理异常: {exc}, request_id={request_id}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "内部服务器错误",
                "request_id": request_id,
            },
        )

    # ---------- 请求追踪中间件 ----------

    @app.middleware("http")
    async def request_tracing(request: Request, call_next):
        """为每个请求分配 ID，记录耗时，并追踪事件"""
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        start_time = time.time()

        response = await call_next(request)

        duration = round((time.time() - start_time) * 1000, 2)
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"-> {response.status_code} ({duration}ms)"
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"

        # 事件追踪 (异步，不阻塞响应)
        try:
            from ..analytics import get_tracker
            tracker = get_tracker()
            if tracker:
                tracker.track("api_request", {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration,
                })
                if response.status_code >= 500:
                    tracker.track("error", {
                        "type": "server_error",
                        "path": request.url.path,
                        "status_code": response.status_code,
                    })
        except Exception:
            pass

        return response

    # ---------- CORS 配置 ----------

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # Auth middleware (checks JWT on all non-public routes)
    from .auth import AuthMiddleware
    app.add_middleware(AuthMiddleware)

    # Register routers
    from .api import router as api_router
    app.include_router(api_router, prefix="/api/v1")

    # Initialize builtin skills registry
    from ..agents.skills import SkillRegistry
    SkillRegistry.initialize_builtin()

    # Health check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": settings.version}

    # Frontend static files (mount if dist exists)
    frontend_dist = get_frontend_dist_dir()
    if frontend_dist:
        logger.info(f"前端静态文件目录: {frontend_dist}")

        @app.get("/")
        async def serve_index():
            return FileResponse(
                str(frontend_dist / "index.html"),
                headers={"Cache-Control": "no-cache"},
            )

        @app.get("/{full_path:path}")
        async def serve_static_or_spa(full_path: str):
            # 跳过 API 与文档路由
            if (
                full_path.startswith("api/")
                or full_path.startswith("docs")
                or full_path.startswith("redoc")
                or full_path == "health"
            ):
                raise HTTPException(status_code=404, detail="Not Found")

            # 尝试提供静态文件
            root = frontend_dist.resolve()
            file_path = (frontend_dist / full_path).resolve()
            if file_path.is_relative_to(root) and file_path.is_file():
                cache_control = (
                    "public, max-age=31536000, immutable"
                    if full_path.startswith("assets/")
                    else "no-cache"
                )
                return FileResponse(
                    str(file_path), headers={"Cache-Control": cache_control}
                )

            # SPA 回退
            return FileResponse(
                str(frontend_dist / "index.html"),
                headers={"Cache-Control": "no-cache"},
            )
    else:
        logger.warning("前端 dist 目录未找到，静态文件服务未启用")

    return app
