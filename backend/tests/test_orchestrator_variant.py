"""
Legacy unit tests for removed deterministic gates.

Phase 3 replaced `_deterministic_rank`, `_validate_full_text`, and
`_apply_downstream_application_gate` with `_select_patents_via_llm`.
Behavioral coverage now lives in tests/test_patent_selection.py.

This module keeps the zero-survivors diagnosis helper coverage.
"""
import uuid

from app.services.pipeline.orchestrator import PipelineOrchestrator


def test_zero_survivors_error_includes_filter_diagnosis():
    orch = PipelineOrchestrator(run_id=uuid.uuid4())
    orch._reset_filter_stats()
    orch._filter_stats.update(
        {
            "selection_reject_variant": 3,
            "selection_reject_downstream": 4,
            "selection_reject_medium": 1,
            "selection_reject_other": 1,
            "selection_related_retain": 2,
            "fetch_failures": 0,
            "extraction_failures": 0,
        }
    )
    msg = orch._format_zero_survivors_error(reached_validation=4)
    assert "0 patents survived the configured selection criteria" in msg
    assert "not a claim that no related patents exist" in msg
    assert "3 qualifier/variant mismatch" in msg
    assert "4 downstream-only" in msg
    assert "2 related/non-primary" in msg
    assert "2 other technical rejections" in msg or "2 other rejections" in msg
