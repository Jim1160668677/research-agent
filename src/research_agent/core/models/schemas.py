"""Schemas for API request/response validation"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, EmailStr, HttpUrl


# ========== User Schemas ==========

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    research_fields: Optional[List[str]] = None
    preferred_models: Optional[List[str]] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str = "researcher"
    is_active: bool = True
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ========== Plugin Schemas ==========

class PluginCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    description: Optional[str] = None
    author: Optional[str] = None
    category: str = Field(default="general")
    tags: List[str] = Field(default_factory=list)
    dependencies: List[Dict[str, str]] = Field(default_factory=list)
    config_schema: Dict[str, Any] = Field(default_factory=dict)


class PluginUpdate(BaseModel):
    version: Optional[str] = None
    latest_version: Optional[str] = None
    description: Optional[str] = None
    config_schema: Optional[Dict[str, Any]] = None
    author: Optional[str] = None
    homepage: Optional[str] = None
    docs_url: Optional[str] = None
    support_email: Optional[str] = None
    status: Optional[Literal["available", "installed", "enabled", "disabled"]] = None


class PluginResponse(BaseModel):
    id: int
    name: str
    version: str
    latest_version: Optional[str] = None
    update_available: Optional[bool] = False
    description: Optional[str] = None
    author: Optional[str] = None
    category: str
    tags: List[str] = Field(default_factory=list)
    icon: Optional[str] = None
    license: Optional[str] = None
    source_url: Optional[str] = None
    homepage: Optional[str] = None
    docs_url: Optional[str] = None
    support_email: Optional[str] = None
    dependencies: List[Dict[str, str]] = Field(default_factory=list)
    downloads: Optional[int] = 0
    rating_avg: Optional[float] = 0.0
    rating_count: Optional[int] = 0
    os_compatibility: List[str] = Field(default_factory=list)
    install_method: Dict[str, Any] = Field(default_factory=dict)
    is_installed: bool
    status: str
    lifecycle_state: str = "discovered"
    is_selected: bool = False
    is_deployed: bool = False
    is_verified: bool = False
    is_enabled: bool = False
    manifest_schema_version: str = "1.0"
    manifest_digest: Optional[str] = None
    source_registry: str = "builtin"
    source_identifier: Optional[str] = None
    source_synced_at: Optional[datetime] = None
    trust_status: str = "unreviewed"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PluginDetailResponse(PluginResponse):
    versions: List[Dict[str, Any]] = Field(default_factory=list)
    rating_summary: Dict[str, Any] = Field(default_factory=dict)


class PluginInstallRequest(BaseModel):
    plugin_id: int
    config: Dict[str, Any] = Field(default_factory=dict)
    version: Optional[str] = None  # 可选: 指定安装版本


class PluginReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    user_id: Optional[int] = None


# ========== Skill Schemas ==========

class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    description: str
    category: str = Field(default="general")
    skill_md: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    executor_type: Literal["python", "shell", "mcp", "http"] = "python"
    executor_config: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


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
    skill_id: Optional[int] = None
    plugin_id: Optional[int] = None
    node_type: Literal["skill", "plugin", "input", "output", "condition"] = "skill"
    config: Dict[str, Any] = Field(default_factory=dict)
    variables: Dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    source: str
    target: str
    condition: Optional[str] = None  # 条件表达式


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    category: str = Field(default="general")
    definition: Dict[str, Any] = Field(..., description="包含nodes和edges的工作流定义")
    variables: Dict[str, Any] = Field(default_factory=dict)
    is_public: bool = False


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    definition: Optional[Dict[str, Any]] = None
    variables: Optional[Dict[str, Any]] = None
    status: Optional[Literal["draft", "active", "archived"]] = None


class WorkflowRunRequest(BaseModel):
    workflow_id: int
    inputs: Dict[str, Any] = Field(default_factory=dict)
    variables: Dict[str, Any] = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category: str
    definition: Dict[str, Any]
    variables: Dict[str, Any]
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
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    progress: int
    current_node: Optional[str]
    duration_seconds: Optional[float]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== Agent Schemas ==========

class AgentMessage(BaseModel):
    content: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    session_id: Optional[str]
    message: str
    tools_used: List[Dict[str, Any]] = Field(default_factory=list)
    skills_executed: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentSession(BaseModel):
    id: int
    user_id: int
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    message_count: int


class AgentSessionResponse(AgentSession):
    messages: List[Dict[str, Any]]


# ========== NCBI Schemas ==========

class PubmedQuery(BaseModel):
    query: str
    max_results: int = Field(default=10, ge=1, le=100)
    sort: str = Field(default="relevance")
    date_range: Optional[Dict[str, str]] = None


class BlastQuery(BaseModel):
    query_sequence: str
    database: str = Field(default="nt")
    program: str = Field(default="blastn")
    max_results: int = Field(default=10, ge=1, le=100)


class SraQuery(BaseModel):
    query: str
    max_results: int = Field(default=10, ge=1, le=100)
    organism: Optional[str] = None
    study_type: Optional[str] = None


class NcbiResponse(BaseModel):
    total_count: int
    results: List[Dict[str, Any]]
    query: str
    timestamp: datetime


# ========== Recommendation Schemas ==========

class RecommendationRequest(BaseModel):
    context_type: str = Field(default="general")
    context_data: Dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1, le=20)


class RecommendationResponse(BaseModel):
    id: int
    user_id: int
    context_type: str
    recommended_items: List[Dict[str, Any]]
    reason: Optional[str]
    confidence: Optional[float]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== Common Schemas ==========

class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None
    errors: Optional[List[str]] = None


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: int
