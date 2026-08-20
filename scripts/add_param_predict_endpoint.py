"""Add param prediction API endpoint to research router."""
from pathlib import Path

API_FILE = Path("src/research_agent/core/api/research.py")
content = API_FILE.read_text(encoding="utf-8")

# Add import for param_predictor at the top imports section
import_line = "from ...reporting.rocrate import generate_rocrate"
if "param_predictor" not in content:
    content = content.replace(
        import_line,
        import_line + '\nfrom ...research.param_predictor import predict_for_new_run, estimate_sample_sufficiency'
    )

# Add a new request model after ReportFormat
old_format = '''class ReportFormat(BaseModel):
    format: Literal["md", "html", "pdf"] = "pdf"'''
new_format = '''class ReportFormat(BaseModel):
    format: Literal["md", "html", "pdf"] = "pdf"


class ParamPredictRequest(BaseModel):
    pipeline_id: str = Field(..., min_length=1, max_length=200)
    revision: str = Field(default="", max_length=80)
    profile: str = Field(default="docker", max_length=40)
    system_memory_gb: float = Field(default=32.0, gt=0, le=1024)
    system_cpus: int = Field(default=8, ge=1, le=256)
    prior_parameters: dict[str, str] = Field(default_factory=dict)'''

content = content.replace(old_format, new_format)

# Add the endpoint before generate_rocrate_export
old_rocrate = '''@router.post("/runs/{run_id}/rocrate")
async def generate_rocrate_export('''

new_section = '''@router.post("/runs/params/predict")
async def predict_run_parameters(
    request: ParamPredictRequest,
    current_user: dict = Depends(get_current_user),
):
    """Predict optimal parameters for a new pipeline run based on historical data."""
    result = await predict_for_new_run(
        user_id=current_user["user_id"],
        pipeline_id=request.pipeline_id,
        revision=request.revision,
        profile=request.profile,
        system_memory_gb=request.system_memory_gb,
        system_cpus=request.system_cpus,
        prior_parameters=request.prior_parameters,
    )
    sufficient, suff_msg = estimate_sample_sufficiency(result.historical_runs_analyzed)
    return {
        "pipeline_id": request.pipeline_id,
        "revision": request.revision or "latest",
        "recommendations": result.to_dict()["recommendations"],
        "confidence": result.confidence,
        "historical_runs_analyzed": result.historical_runs_analyzed,
        "data_sufficiency": {"sufficient": sufficient, "message": suff_msg},
        "warnings": result.warnings,
    }


@router.post("/runs/{run_id}/rocrate")
async def generate_rocrate_export('''

if old_rocrate in content and new_section not in content:
    content = content.replace(old_rocrate, new_section)
    print("Endpoint added successfully")
else:
    print("WARNING: Could not find exact match or endpoint already exists")
    if new_section in content:
        print("Endpoint already exists in file")

API_FILE.write_text(content, encoding="utf-8")
