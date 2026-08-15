"""API routes"""

from fastapi import APIRouter

from ..app import settings

router = APIRouter()


@router.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": settings.app_name}


# Import and include sub-routers
from . import (
    agents,
    analytics,
    auth,
    docking,
    llm,
    ncbi,
    pipelines,
    plugins,
    recommendations,
    research,
    skills,
    system,
    workflows,
)

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
router.include_router(agents.router, prefix="/agents", tags=["agents"])
router.include_router(plugins.router, prefix="/plugins", tags=["plugins"])
router.include_router(ncbi.router, prefix="/ncbi", tags=["ncbi"])
router.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
router.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
router.include_router(skills.router, prefix="/skills", tags=["skills"])
router.include_router(docking.router, prefix="/docking", tags=["docking"])
router.include_router(llm.router, prefix="/llm", tags=["llm"])
router.include_router(system.router, prefix="/system", tags=["system"])
router.include_router(research.router, prefix="/research", tags=["research"])
router.include_router(pipelines.router, prefix="/pipelines", tags=["pipelines"])


__all__ = ["router"]
