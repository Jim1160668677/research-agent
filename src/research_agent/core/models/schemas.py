"""Schemas for API request/response validation"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ========== User Schemas ==========

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    research_fields: list[str] | None = None
    preferred_models: list[str] | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str = "researcher"
    is_active: bool = True
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ========== Plugin Schemas ==========

class PluginCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    description: str | None = None
    author: str | None = None
    category: str = Field(default="general")
    tags: list[str] = Field(default_factory=list)
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)


class PluginUpdate(BaseModel):
    version: str | None = None
    latest_version: str | None = None
    description: str | None = None
    config_schema: dict[str, Any] | None = None
    author: str | None = None
    homepage: str | None = None
    docs_url: str | None = None
    support_email: str | None = None
    status: Literal["available", "installed", "enabled", "disabled"] | None = None


class PluginResponse(BaseModel):
    id: int
    name: str
    version: str
    latest_version: str | None = None
    update_available: bool | None = False
    description: str | None = None
    author: str | None = None
    category: str
    tags: list[str] = Field(default_factory=list)
    icon: str | None = None
    license: str | None = None
    source_url: str | None = None
    homepage: str | None = None
    docs_url: str | None = None
    support_email: str | None = None
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    downloads: int | None = 0
    rating_avg: float | None = 0.0
    rating_count: int | None = 0
    os_compatibility: list[str] = Field(default_factory=list)
    install_method: dict[str, Any] = Field(default_factory=dict)
    is_installed: bool
    status: str
    lifecycle_state: str = "discovered"
    is_selected: bool = False
    is_deployed: bool = False
    is_verified: bool = False
    is_enabled: bool = False
    manifest_schema_version: str = "1.0"
    manifest_digest: str | None = None
    source_registry: str = "builtin"
    source_identifier: str | None = None
    source_synced_at: datetime | None = None
    trust_status: str = "unreviewed"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PluginDetailResponse(PluginResponse):
    versions: list[dict[str, Any]] = Field(default_factory=list)
    rating_summary: dict[str, Any] = Field(default_factory=dict)


class PluginInstallRequest(BaseModel):
    plugin_id: int
    config: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None  # 可选: 指定安装版本


class PluginReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None
    user_id: int | None = None


# ========== Skill Schemas ==========

class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    description: str
    category: str = Field(default="general")
    skill_md: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    executor_type: Literal["python", "shell", "mcp", "http"] = "python"
    executor_config: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class SkillResponse(BaseModel):
    id: int
    name: str
    version: str
    description: str
    category: str
    executor_type: str
    is_active: bool
    is_builtin: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== Workflow Schemas ==========

class WorkflowNode(BaseModel):
    name: str
    skill_id: int | None = None
    plugin_id: int | None = None
    node_type: Literal["skill", "plugin", "input", "output", "condition"] = "skill"
    config: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    source: str
    target: str
    condition: str | None = None  # 条件表达式


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    category: str = Field(default="general")
    definition: dict[str, Any] = Field(..., description="包含nodes和edges的工作流定义")
    variables: dict[str, Any] = Field(default_factory=dict)
    is_public: bool = False


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
    status: Literal["draft", "active", "archived"] | None = None


class WorkflowRunRequest(BaseModel):
    workflow_id: int
    inputs: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    id: int
    name: str
    description: str | None
    category: str
    definition: dict[str, Any]
    variables: dict[str, Any]
    is_public: bool
    status: str
    version: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkflowRunResponse(BaseModel):
    id: int
    workflow_id: int
    status: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    progress: int
    current_node: str | None
    duration_seconds: float | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== Agent Schemas ==========

class AgentMessage(BaseModel):
    content: str = Field(..., min_length=1)
    session_id: str | None = None
    context: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    session_id: str | None
    message: str
    tools_used: list[dict[str, Any]] = Field(default_factory=list)
    skills_executed: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSession(BaseModel):
    id: int
    user_id: int
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int


class AgentSessionResponse(AgentSession):
    messages: list[dict[str, Any]]


# ========== NCBI Schemas ==========

class PubmedQuery(BaseModel):
    query: str
    max_results: int = Field(default=10, ge=1, le=100)
    sort: str = Field(default="relevance")
    date_range: dict[str, str] | None = None


class BlastQuery(BaseModel):
    query_sequence: str
    database: str = Field(default="nt")
    program: str = Field(default="blastn")
    max_results: int = Field(default=10, ge=1, le=100)


class SraQuery(BaseModel):
    query: str
    max_results: int = Field(default=10, ge=1, le=100)
    organism: str | None = None
    study_type: str | None = None


class NcbiResponse(BaseModel):
    total_count: int
    results: list[dict[str, Any]]
    query: str
    timestamp: datetime


# ========== Recommendation Schemas ==========

class RecommendationRequest(BaseModel):
    context_type: str = Field(default="general")
    context_data: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1, le=20)


class RecommendationResponse(BaseModel):
    id: int
    user_id: int
    context_type: str
    recommended_items: list[dict[str, Any]]
    reason: str | None
    confidence: float | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== Common Schemas ==========

class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
    errors: list[str] | None = None


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    total_pages: int


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: int
