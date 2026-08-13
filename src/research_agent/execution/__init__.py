"""Versioned external execution backends for scientific pipelines."""

from .manager import get_pipeline_manager, recover_pipeline_runs, shutdown_pipeline_manager
from .nextflow import NextflowBackend, pipeline_catalog

__all__ = [
    "NextflowBackend",
    "get_pipeline_manager",
    "pipeline_catalog",
    "recover_pipeline_runs",
    "shutdown_pipeline_manager",
]
