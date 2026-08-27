# Migration Log

This document lists all test/debug scripts and logs that were relocated during the file reorganization.

## `run_pipeline_scripts/` (Pipeline execution entry points)
- `run_pipeline.py` -> `run_pipeline_scripts/run_pipeline.py`
- `run_pipeline_acn.py` -> `run_pipeline_scripts/run_pipeline_acn.py`
- `run_pipeline_high_acn.py` -> `run_pipeline_scripts/run_pipeline_high_acn.py`
- `run_pipeline_mw_nbr.py` -> `run_pipeline_scripts/run_pipeline_mw_nbr.py`
- `run_pipeline_xnbr.py` -> `run_pipeline_scripts/run_pipeline_xnbr.py`

## `dev-scripts/pipeline-checks/` (Manual pipeline tests)
- `test_gp_pipeline.py` -> `dev-scripts/pipeline-checks/test_gp_pipeline.py`
- `test_high_acn.py` -> `dev-scripts/pipeline-checks/test_high_acn.py`
- `test_pipeline.py` -> `dev-scripts/pipeline-checks/test_pipeline.py`
- `test_pipeline_architecture.py` -> `dev-scripts/pipeline-checks/test_pipeline_architecture.py`
- `test_real_pipeline.py` -> `dev-scripts/pipeline-checks/test_real_pipeline.py`
- `scratch/test_full.py` -> `dev-scripts/pipeline-checks/test_full.py`
- `scratch/test_full_pipeline_gp.py` -> `dev-scripts/pipeline-checks/test_full_pipeline_gp.py`
- `scratch/test_live_run.py` -> `dev-scripts/pipeline-checks/test_live_run.py`
- `scripts/e2e_full_pipeline_test.py` -> `dev-scripts/pipeline-checks/e2e_full_pipeline_test.py`
- `scripts/test_pipeline_run.py` -> `dev-scripts/pipeline-checks/test_pipeline_run.py`
- `scripts/e2e_audit_runner.py` -> `dev-scripts/pipeline-checks/e2e_audit_runner.py`
- `scripts/e2e_jurisdiction_audit.py` -> `dev-scripts/pipeline-checks/e2e_jurisdiction_audit.py`
- `scripts/e2e_phase2_audit.py` -> `dev-scripts/pipeline-checks/e2e_phase2_audit.py`

## `dev-scripts/query-experiments/` (Query expansion and search tests)
- `test_queries_target.py` -> `dev-scripts/query-experiments/test_queries_target.py`
- `test_query_expansion.py` -> `dev-scripts/query-experiments/test_query_expansion.py`
- `test_query_expansion_integration.py` -> `dev-scripts/query-experiments/test_query_expansion_integration.py`
- `test_query_to_search_handoff.py` -> `dev-scripts/query-experiments/test_query_to_search_handoff.py`
- `scratch/test_build_queries.py` -> `dev-scripts/query-experiments/test_build_queries.py`
- `scratch/test_db_query.py` -> `dev-scripts/query-experiments/test_db_query.py`
- `scratch/test_queries.py` -> `dev-scripts/query-experiments/test_queries.py`
- `scratch/test_queries_target2.py` -> `dev-scripts/query-experiments/test_queries_target2.py`
- `scripts/test_query_expansion.py` -> `dev-scripts/query-experiments/test_query_expansion_scripts.py`
- `scripts/test_query_expansion_diag.py` -> `dev-scripts/query-experiments/test_query_expansion_diag.py`

## `dev-scripts/misc/` (Miscellaneous debug scripts and mocks)
- `check_db.py` -> `dev-scripts/misc/check_db.py`
- `scratch/check_db.py` -> `dev-scripts/misc/check_db_scratch.py`
- `scripts/check_db.py` -> `dev-scripts/misc/check_db_scripts.py`
- `test_serper.py` -> `dev-scripts/misc/test_serper.py`
- `scratch/test_serper.py` -> `dev-scripts/misc/test_serper_scratch.py`
- `mock_dir/` -> `dev-scripts/misc/mock_dir/`
- `test_compound.py` -> `dev-scripts/misc/test_compound.py`
- `test_controlled.py` -> `dev-scripts/misc/test_controlled.py`
- `test_data_preservation.py` -> `dev-scripts/misc/test_data_preservation.py`
- `test_discovery_components.py` -> `dev-scripts/misc/test_discovery_components.py`
- `test_enum.py` -> `dev-scripts/misc/test_enum.py`
- `test_enum_persist.py` -> `dev-scripts/misc/test_enum_persist.py`
- `test_env.py` -> `dev-scripts/misc/test_env.py`
- `test_minimal.py` -> `dev-scripts/misc/test_minimal.py`
- `test_report_schema.py` -> `dev-scripts/misc/test_report_schema.py`
- `test_schema.py` -> `dev-scripts/misc/test_schema.py`
- `scratch/demote_logs.py` -> `dev-scripts/misc/demote_logs.py`
- `scratch/demote_search_logs.py` -> `dev-scripts/misc/demote_search_logs.py`
- `scratch/diag_bugs.py` -> `dev-scripts/misc/diag_bugs.py`
- `scratch/diagnose_admin.py` -> `dev-scripts/misc/diagnose_admin.py`
- `scratch/run_mocks.py` -> `dev-scripts/misc/run_mocks.py`
- `scratch/run_test.py` -> `dev-scripts/misc/run_test.py`
- `scratch/sim_scores.py` -> `dev-scripts/misc/sim_scores.py`
- `scratch/telemetry_precheck.py` -> `dev-scripts/misc/telemetry_precheck.py`
- `scratch/test_admin_router.py` -> `dev-scripts/misc/test_admin_router.py`
- `scratch/test_api_report.py` -> `dev-scripts/misc/test_api_report.py`
- `scratch/test_curl.ps1` -> `dev-scripts/misc/test_curl.ps1`
- `scratch/test_db_report.py` -> `dev-scripts/misc/test_db_report.py`
- `scratch/test_gp_endpoints.py` -> `dev-scripts/misc/test_gp_endpoints.py`
- `scratch/test_gp_headers.py` -> `dev-scripts/misc/test_gp_headers.py`
- `scratch/test_gp_html.py` -> `dev-scripts/misc/test_gp_html.py`
- `scratch/test_gp_page.py` -> `dev-scripts/misc/test_gp_page.py`
- `scratch/test_gp_session.py` -> `dev-scripts/misc/test_gp_session.py`
- `scratch/test_sanitizer.py` -> `dev-scripts/misc/test_sanitizer.py`
- `scratch/test_sanitizer_bug.py` -> `dev-scripts/misc/test_sanitizer_bug.py`
- `scratch/test_url_encoding.py` -> `dev-scripts/misc/test_url_encoding.py`
- `scratch/trigger_run.py` -> `dev-scripts/misc/trigger_run.py`
- `scratch/verify_tokens.py` -> `dev-scripts/misc/verify_tokens.py`
- `scripts/reset_config.py` -> `dev-scripts/misc/reset_config.py`
- `scripts/reset_dev_users.py` -> `dev-scripts/misc/reset_dev_users.py`
- `scripts/test_1.py` -> `dev-scripts/misc/test_1.py`
- `scripts/test_2.py` -> `dev-scripts/misc/test_2.py`
- `scripts/test_3.py` -> `dev-scripts/misc/test_3.py`
- `scripts/test_4.py` -> `dev-scripts/misc/test_4.py`
- `scripts/test_llm_isolation.py` -> `dev-scripts/misc/test_llm_isolation.py`
- `scripts/test_telemetry.py` -> `dev-scripts/misc/test_telemetry.py`
- `scripts/verify_telemetry.py` -> `dev-scripts/misc/verify_telemetry.py`

## `dev-logs/` (Test logs and dumps)
- `audit_phase1.log` -> `dev-logs/audit_phase1.log`
- `audit_phase1_groq.log` -> `dev-logs/audit_phase1_groq.log`
- `audit_phase1_v2.log` -> `dev-logs/audit_phase1_v2.log`
- `audit_phase1_v3.log` -> `dev-logs/audit_phase1_v3.log`
- `jurisdiction_audit.log` -> `dev-logs/jurisdiction_audit.log`
- `out.log` -> `dev-logs/out.log`
- `raw_schema.json` -> `dev-logs/raw_schema.json`
- `schemas_history.txt` -> `dev-logs/schemas_history.txt`
- `test_logs.txt` -> `dev-logs/test_logs.txt`
- `scratch/test_fallback.log` -> `dev-logs/test_fallback.log`
- `scratch/test_gp_503.log` -> `dev-logs/test_gp_503.log`
- `scratch/test_output_4.log` -> `dev-logs/test_output_4.log`
- `scratch/test_output_5.log` -> `dev-logs/test_output_5.log`
- `scratch/test_output_6.log` -> `dev-logs/test_output_6.log`
- `scratch/test_pipeline_output.log` -> `dev-logs/test_pipeline_output.log`
- `scratch/diff_orch.txt` -> `dev-logs/diff_orch.txt`
- `scratch/diff_schemas.txt` -> `dev-logs/diff_schemas.txt`
- `scratch/diff_search.txt` -> `dev-logs/diff_search.txt`
- `scratch/out.txt` -> `dev-logs/out.txt`
- `scripts/adaptive_audit.log` -> `dev-logs/adaptive_audit.log`
- `scripts/adaptive_audit_final.log` -> `dev-logs/adaptive_audit_final.log`
