"""Database models"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="researcher")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    profiles = relationship("UserProfile", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = ()


class UserProfile(Base):
    """用户档案 - 存储科研领域、偏好等"""
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    research_fields = Column(JSON, default=list)  # 研究领域: ["genomics", "proteomics"]
    preferred_models = Column(JSON, default=list)  # 偏好的AI模型
    skill_preferences = Column(JSON, default=dict)  # 技能偏好设置
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="profiles")

    __table_args__ = (
        Index("ix_user_profiles_user_id", "user_id"),
    )


class UserSession(Base):
    """用户会话 - 记录对话历史"""
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_token = Column(String(255), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", back_populates="sessions")
    messages = relationship("SessionMessage", back_populates="session", cascade="all, delete-orphan",
                           order_by="SessionMessage.created_at")

    __table_args__ = (
        Index("ix_user_sessions_user_id", "user_id"),
    )


class SessionMessage(Base):
    """会话消息"""
    __tablename__ = "session_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("user_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # "user", "assistant", "system"
    content = Column(Text, nullable=False)
    extra = Column(JSON, default=dict)  # 附加元数据（工具调用、引用等）
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    session = relationship("UserSession", back_populates="messages")

    __table_args__ = (
        Index("ix_session_messages_session_id", "session_id"),
    )


class Plugin(Base):
    """插件定义"""
    __tablename__ = "plugins"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    version = Column(String(20), nullable=False)
    latest_version = Column(String(20))  # 市场最新版本 (用于更新检测)
    description = Column(Text)
    author = Column(String(100))
    category = Column(String(50), index=True)  # genomics, proteomics, docking, structure, etc.
    tags = Column(JSON, default=list)
    icon = Column(String(255))
    source_url = Column(String(500))
    license = Column(String(50))

    # Dependencies
    dependencies = Column(JSON, default=list)  # [{"name": "...", "version": "..."}]
    required_env = Column(JSON, default=list)  # 需要的环境变量

    # 市场信息
    downloads = Column(Integer, default=0)  # 安装/下载次数
    rating_avg = Column(Float, default=0.0)  # 平均评分 0-5
    rating_count = Column(Integer, default=0)  # 评分人数
    homepage = Column(String(500))  # 官网
    docs_url = Column(String(500))  # 文档地址
    support_email = Column(String(100))  # 技术支持邮箱
    os_compatibility = Column(JSON, default=list)  # ["windows","linux","macos"]
    install_method = Column(JSON, default=dict)  # 一键部署方式: {"method": "conda|pip|binary|manual", ...}

    # Installation
    # Versioned capability contract and catalog provenance. Marketplace
    # discovery is deliberately separate from per-user deployment state.
    manifest_schema_version = Column(String(20), default="1.0")
    manifest = Column(JSON, default=dict)
    manifest_digest = Column(String(64))
    source_registry = Column(String(50), default="builtin", index=True)
    source_identifier = Column(String(255), index=True)
    source_metadata = Column(JSON, default=dict)
    source_synced_at = Column(DateTime)
    trust_status = Column(String(20), default="curated", index=True)

    # RA-Eval v1: 断言型冒烟用例 [{id, command, args, expect_exit, expect_stdout, timeout_s}]
    smoke_tests = Column(JSON, default=list)

    is_installed = Column(Boolean, default=False)
    installed_at = Column(DateTime)
    installed_by = Column(Integer, ForeignKey("users.id"))

    # Status
    status = Column(String(20), default="available")  # available, installed, enabled, disabled
    config_schema = Column(JSON, default=dict)  # 插件配置Schema

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    versions = relationship("PluginVersion", back_populates="plugin", cascade="all, delete-orphan",
                            order_by="PluginVersion.created_at.asc()")
    reviews = relationship("PluginReview", back_populates="plugin", cascade="all, delete-orphan",
                           order_by="PluginReview.created_at.asc()")

    __table_args__ = ()


class PluginVersion(Base):
    """插件版本历史 - 版本控制机制"""
    __tablename__ = "plugin_versions"

    id = Column(Integer, primary_key=True, index=True)
    plugin_id = Column(Integer, ForeignKey("plugins.id"), nullable=False)
    version = Column(String(20), nullable=False)
    release_date = Column(String(20))  # YYYY-MM-DD
    changelog = Column(Text)  # 更新说明
    size_mb = Column(Float)  # 安装包大小
    checksum = Column(String(64))  # SHA256 校验和
    download_url = Column(String(500))
    is_latest = Column(Boolean, default=False)  # 是否为最新版本

    # Status
    is_active = Column(Boolean, default=True)  # 可安装/可回滚
    requires_manual = Column(Boolean, default=False)  # 需要手动部署

    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    plugin = relationship("Plugin", back_populates="versions")

    __table_args__ = (
        Index("ix_plugin_versions_plugin_id", "plugin_id"),
    )


class PluginReview(Base):
    """插件用户评价"""
    __tablename__ = "plugin_reviews"

    id = Column(Integer, primary_key=True, index=True)
    plugin_id = Column(Integer, ForeignKey("plugins.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rating = Column(Integer, nullable=False)  # 1-5 星
    comment = Column(Text)
    is_verified = Column(Boolean, default=False)  # 是否已验证（已安装用户）

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    plugin = relationship("Plugin", back_populates="reviews")

    __table_args__ = (
        Index("ix_plugin_reviews_plugin_id", "plugin_id"),
    )


class PluginSmokeRun(Base):
    """插件冒烟评测记录（RA-Eval v1）"""

    __tablename__ = "plugin_smoke_runs"

    id = Column(Integer, primary_key=True, index=True)
    plugin_id = Column(Integer, ForeignKey("plugins.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    smoke_id = Column(String(80), nullable=False)
    status = Column(String(20), nullable=False, index=True)  # passed | failed
    detail = Column(JSON, default=dict)
    duration_ms = Column(Integer, default=0)
    run_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_plugin_smoke_plugin_run", "plugin_id", "run_at"),
    )


class PluginInstallation(Base):
    """插件安装记录"""
    __tablename__ = "plugin_installations"

    id = Column(Integer, primary_key=True, index=True)
    plugin_id = Column(Integer, ForeignKey("plugins.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    version = Column(String(20), nullable=True)
    config = Column(JSON, default=dict)
    status = Column(String(20), default="selected")
    error_message = Column(Text)
    installed_at = Column(DateTime, server_default=func.now())
    state_changed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    provenance = Column(JSON, default=dict)

    # Relationships
    plugin = relationship("Plugin")

    __table_args__ = (
        Index("ix_plugin_installations_plugin_id", "plugin_id"),
        Index("ix_plugin_installations_user_id", "user_id"),
        Index("ix_plugin_installations_user_plugin_state", "user_id", "plugin_id", "status"),
    )


class CatalogSync(Base):
    """Immutable summary of a trusted external catalog synchronization."""

    __tablename__ = "catalog_syncs"

    id = Column(Integer, primary_key=True, index=True)
    registry = Column(String(50), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="running", index=True)
    source_urls = Column(JSON, default=list)
    request = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    source_digest = Column(String(64))
    cache_status = Column(String(20))
    error_message = Column(Text)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)

    __table_args__ = (
        Index("ix_catalog_syncs_registry_started", "registry", "started_at"),
    )


class Skill(Base):
    """技能定义 - 标准化的可执行单元"""
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    version = Column(String(20), nullable=False)
    description = Column(Text)
    category = Column(String(50), index=True)

    # Skill content
    skill_md = Column(Text)  # SKILL.md内容
    parameters = Column(JSON, default=dict)  # 参数定义Schema
    output_schema = Column(JSON, default=dict)  # 输出Schema

    # Execution
    executor_type = Column(String(20), default="python")  # python, shell, mcp, http
    executor_config = Column(JSON, default=dict)

    # Metadata
    tags = Column(JSON, default=list)
    author = Column(String(100))
    source = Column(String(255))  # 来源：内置、社区、用户上传
    license = Column(String(50))

    # Status
    is_active = Column(Boolean, default=True)
    is_builtin = Column(Boolean, default=False)  # 是否为内置技能

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = ()


class Workflow(Base):
    """工作流定义"""
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(50), index=True)

    # Workflow definition
    definition = Column(JSON, nullable=False)  # DAG定义: nodes + edges
    variables = Column(JSON, default=dict)  # 变量定义

    # Metadata
    tags = Column(JSON, default=list)
    author = Column(Integer, ForeignKey("users.id"))
    is_public = Column(Boolean, default=False)
    version = Column(String(20), default="1.0.0")

    # Status
    status = Column(String(20), default="draft")  # draft, active, archived

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    runs = relationship("WorkflowRun", back_populates="workflow", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_workflows_status", "status"),
        Index("ix_workflows_author", "author"),
    )


class WorkflowRun(Base):
    """工作流执行记录"""
    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))

    # Execution
    status = Column(String(20), default="running")  # pending, running, completed, failed, cancelled
    inputs = Column(JSON, default=dict)  # 输入参数
    outputs = Column(JSON, default=dict)  # 输出结果
    errors = Column(JSON, default=list)  # 错误信息

    # Progress
    progress = Column(Integer, default=0)  # 0-100
    current_node = Column(String(100))  # 当前执行节点

    # Timing
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_seconds = Column(Integer)

    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="runs")
    steps = relationship("WorkflowStep", back_populates="run", cascade="all, delete-orphan",
                        order_by="WorkflowStep.order")

    __table_args__ = (
        Index("ix_workflow_runs_workflow_id", "workflow_id"),
        Index("ix_workflow_runs_status", "status"),
        Index("ix_workflow_runs_user_id", "user_id"),
    )


class WorkflowStep(Base):
    """工作流执行步骤"""
    __tablename__ = "workflow_steps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    node_name = Column(String(100), nullable=False)
    order = Column(Integer, nullable=False)

    status = Column(String(20), default="pending")  # pending, running, completed, failed
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    errors = Column(JSON, default=list)

    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_seconds = Column(Integer)

    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    run = relationship("WorkflowRun", back_populates="steps")

    __table_args__ = (
        Index("ix_workflow_steps_run_id", "run_id"),
        Index("ix_workflow_steps_order", "run_id", "order"),
    )


class Recommendation(Base):
    """推荐记录"""
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    context_type = Column(String(50), nullable=False)  # skill, plugin, workflow, literature
    context_id = Column(String(100))  # 相关ID
    recommended_items = Column(JSON, default=list)  # 推荐的项目列表

    # Metadata
    reason = Column(Text)  # 推荐理由
    confidence = Column(Float)  # 置信度 0-1

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_recommendations_user_id", "user_id"),
        Index("ix_recommendations_context", "context_type", "context_id"),
    )


class ApiKey(Base):
    """API Key 安全存储 - 使用Fernet加密存储"""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(50), nullable=False, index=True)  # openai/anthropic/google
    name = Column(String(100), default="")  # 备注名
    encrypted_key = Column(Text, nullable=False)  # Fernet加密后的key
    key_prefix = Column(String(20))  # 明文前缀用于展示 (如 sk-...abcd)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Conversation(Base):
    """LLM对话记录"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    session_id = Column(String(100), index=True)  # 会话标识
    provider = Column(String(50))
    model = Column(String(100))
    messages = Column(JSON, default=list)  # [{role, content, timestamp}]
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    """审计日志 - 记录所有敏感操作"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)  # CREATE/UPDATE/DELETE/LOGIN/LOGOUT
    resource = Column(String(100), nullable=False)  # 资源类型
    resource_id = Column(String(100), nullable=True)  # 资源ID
    detail = Column(JSON, default=dict)  # 操作详情
    ip_address = Column(String(45), nullable=True)  # IPv4/IPv6
    user_agent = Column(String(500), nullable=True)
    request_id = Column(String(50), nullable=True)  # 请求追踪ID
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    chain_index = Column(Integer, nullable=True, index=True)
    previous_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=True, index=True)
    chain_version = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    # Relationships
    user = relationship("User")

    __table_args__ = (
        Index("ix_audit_logs_user_action", "user_id", "action"),
        Index("ix_audit_logs_resource", "resource", "resource_id"),
        Index("ux_audit_logs_chain_index", "chain_index", unique=True),
    )


class ResearchRun(Base):
    """可恢复、可审计的科研任务运行记录。"""

    __tablename__ = "research_runs"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    objective = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="pending", index=True)
    plan = Column(JSON, default=dict)
    context = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    evidence = Column(JSON, default=list)
    policy = Column(JSON, default=dict)
    budget = Column(JSON, default=dict)
    progress = Column(Integer, default=0)
    current_step = Column(String(100))
    cancel_requested = Column(Boolean, default=False)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    steps = relationship(
        "ResearchRunStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ResearchRunStep.order",
    )

    __table_args__ = (
        Index("ix_research_runs_user_created", "user_id", "created_at"),
        Index("ix_research_runs_user_status", "user_id", "status"),
    )


class ResearchRunStep(Base):
    """科研任务中的一个有依赖关系的能力调用。"""

    __tablename__ = "research_run_steps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String(36), ForeignKey("research_runs.id"), nullable=False)
    step_key = Column(String(100), nullable=False)
    order = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    capability = Column(String(100), nullable=False, index=True)
    dependencies = Column(JSON, default=list)
    status = Column(String(30), nullable=False, default="pending", index=True)
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    warnings = Column(JSON, default=list)
    error = Column(Text)
    attempts = Column(Integer, default=0)
    confidence = Column(Float, default=0.0)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())

    run = relationship("ResearchRun", back_populates="steps")

    __table_args__ = (
        Index("ix_research_steps_run_order", "run_id", "order"),
        Index("ux_research_steps_run_key", "run_id", "step_key", unique=True),
    )


class PipelineRun(Base):
    """Auditable execution record for an allowlisted external scientific pipeline."""

    __tablename__ = "pipeline_runs"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("research_runs.id"), nullable=True, index=True)
    backend = Column(String(50), nullable=False, default="nextflow")
    pipeline_id = Column(String(150), nullable=False, index=True)
    revision = Column(String(80), nullable=False)
    profile = Column(String(40), nullable=False)
    status = Column(String(30), nullable=False, default="planned", index=True)
    parameters = Column(JSON, default=dict)
    artifact_bindings = Column(JSON, default=dict)
    plan = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    provenance = Column(JSON, default=dict)
    network_allowed = Column(Boolean, nullable=False, default=True)
    timeout_seconds = Column(Integer, nullable=False, default=86400)
    resume_requested = Column(Boolean, nullable=False, default=False)
    resume_count = Column(Integer, nullable=False, default=0)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    exit_code = Column(Integer)
    error = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_pipeline_runs_user_created", "user_id", "created_at"),
        Index("ix_pipeline_runs_user_status", "user_id", "status"),
    )


class ResearchArtifact(Base):
    """用户隔离的科研输入、输出与多模态文件元数据。"""

    __tablename__ = "research_artifacts"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("research_runs.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    relative_path = Column(String(1000), nullable=False)
    media_type = Column(String(150), nullable=False)
    kind = Column(String(30), nullable=False, default="input")
    size_bytes = Column(Integer, nullable=False, default=0)
    sha256 = Column(String(64), nullable=False, index=True)
    encryption_format = Column(String(30), nullable=True)
    encrypted_sha256 = Column(String(64), nullable=True)
    summary = Column(JSON, default=dict)
    status = Column(String(30), nullable=False, default="ready")
    created_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_research_artifacts_user_created", "user_id", "created_at"),
    )


class AgentFeedback(Base):
    """对科研运行结果的显式用户反馈。"""

    __tablename__ = "agent_feedback"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("research_runs.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    accepted = Column(Boolean, nullable=False, default=False)
    correction = Column(Text)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class LearningProposal(Base):
    """待人工审核的学习提案；不会自动改变智能体行为。"""

    __tablename__ = "learning_proposals"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_run_id = Column(String(36), ForeignKey("research_runs.id"), nullable=False)
    title = Column(String(200), nullable=False)
    rationale = Column(Text, nullable=False)
    proposed_change = Column(JSON, nullable=False, default=dict)
    evidence = Column(JSON, default=list)
    status = Column(String(30), nullable=False, default="pending", index=True)
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_learning_proposals_user_status", "user_id", "status"),
    )


# Export Base for migrations
__all__ = [
    "Base",
    "User",
    "UserProfile",
    "UserSession",
    "SessionMessage",
    "Plugin",
    "PluginInstallation",
    "PluginVersion",
    "PluginReview",
    "CatalogSync",
    "Skill",
    "Workflow",
    "WorkflowRun",
    "WorkflowStep",
    "Recommendation",
    "ApiKey",
    "Conversation",
    "AuditLog",
    "ResearchRun",
    "ResearchRunStep",
    "PipelineRun",
    "ResearchArtifact",
    "AgentFeedback",
    "LearningProposal",
]
