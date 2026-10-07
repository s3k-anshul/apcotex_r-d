"""
app/models/__init__.py

Import all models here so Alembic's env.py registers them all with
Base.metadata by importing this single package.
"""
from app.models.user import User, UserRole
from app.models.research_run import ResearchRun, RunStatus
from app.models.report_metadata import ReportMetadata
from app.models.report_file import ReportFile, ReportFileType
from app.models.app_config import AppConfig
from app.models.patent_document import PatentDocument
from app.models.patent_extraction import PatentExtraction
from app.models.extracted_parameter import ExtractedParameter
from app.models.search_query import SearchQueryModel, SearchQueryStatus
from app.models.search_result import SearchResult, TitleScreeningStatus
from app.models.extraction_batch import ExtractionBatch, BatchStatus
from app.models.audit_log import AuditLog

from app.models.api_usage_log import APIUsageLog
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
from app.models.recipe_candidate import RecipeCandidate
from app.models.customer_trial import CustomerTrial, TrialStatus
from app.models.optimized_recipe_candidate import OptimizedRecipeCandidate
from app.models.saved_recipe import SavedRecipe, SavedRecipeStatus

__all__ = [
    "User",
    "UserRole",
    "ResearchRun",
    "RunStatus",
    "ReportMetadata",
    "ReportFile",
    "ReportFileType",
    "AppConfig",
    "PatentDocument",
    "PatentExtraction",
    "ExtractedParameter",
    "SearchQueryModel",
    "SearchQueryStatus",
    "SearchResult",
    "TitleScreeningStatus",
    "ExtractionBatch",
    "BatchStatus",
    "AuditLog",
    "APIUsageLog",
    "RecipeCycle",
    "RecipeCycleStatus",
    "RecipeCandidate",
    "CustomerTrial",
    "TrialStatus",
    "OptimizedRecipeCandidate",
    "SavedRecipe",
    "SavedRecipeStatus",
]
