import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import AsyncSessionLocal
from app.models.recipe_cycle import RecipeCycle, RecipeCycleStatus
from app.models.report_metadata import ReportMetadata
from app.models.user import User
from app.services.recipe_service import RecipeService
from app.services.target_validation_service import TargetValidationService
from app.models.customer_trial import CustomerTrial, TrialStatus
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as session:
        # Check report
        report_stmt = select(ReportMetadata).order_by(ReportMetadata.created_at.desc())
        res = await session.execute(report_stmt)
        reports = res.scalars().all()
        print(f"Found {len(reports)} patent reports:")
        for r in reports[:3]:
            print(f" - Report {r.id}: {r.title}")

        report_id = None
        for r in reports:
            if "nbr" in str(r.title).lower() or "carboxylated" in str(r.title).lower():
                report_id = r.id
                print(f"Selected NBR Report: {report_id} ({r.title})")
                break
        if not report_id and reports:
            report_id = reports[0].id
            print(f"Using latest Report: {report_id} ({reports[0].title})")

        user_stmt = select(User).limit(1)
        res_u = await session.execute(user_stmt)
        user = res_u.scalar_one_or_none()
        user_id = user.id if user else uuid.uuid4()

        # 8 Properties exact scenario
        target_props = [
            {"property": "BACN", "target": "28", "min": "26", "max": "30", "unit": "%"},
            {"property": "Mooney (ML1+4 @ 100°C)", "target": "50", "min": "45", "max": "55", "unit": "MU"},
            {"property": "Stress Relaxation", "target": "0.12", "min": "0.10", "max": "0.15", "unit": ""},
            {"property": "pH", "target": "8.5", "min": "8.0", "max": "9.0", "unit": ""},
            {"property": "Total Solid Content", "target": "42", "min": "40", "max": "45", "unit": "%"},
            {"property": "Gel Content", "target": "75", "min": "70", "max": "80", "unit": "%"},
            {"property": "Tg", "target": "-25", "min": "-28", "max": "-22", "unit": "°C"},
            {"property": "Volatile Matter", "target": "0.4", "min": "0.2", "max": "0.5", "unit": "%"},
        ]

        normalized = TargetValidationService.normalize_target_properties(target_props)
        print(f"Normalized targets: {len(normalized)}")
        assert len(normalized) == 8, f"Expected 8 normalized targets, got {len(normalized)}"

        # Verify all 8 preserve Target + Range
        for tp in normalized:
            disp = tp.display_target()
            print(f"  * {tp.name}: {disp}")
            assert "Target:" in disp and "Range:" in disp

        # Verify candidate scoring priority
        # Candidate 1: perfect target values
        cand_perfect = {
            "name": "Perfect Match Candidate",
            "compound": "7% carboxylated NBR",
            "predicted_properties": [
                {"property": "BACN", "predicted_value": 28.0, "unit": "%"},
                {"property": "Mooney (ML1+4 @ 100°C)", "predicted_value": 50.0, "unit": "MU"},
                {"property": "Stress Relaxation", "predicted_value": 0.12, "unit": ""},
                {"property": "pH", "predicted_value": 8.5, "unit": ""},
                {"property": "Total Solid Content", "predicted_value": 42.0, "unit": "%"},
                {"property": "Gel Content", "predicted_value": 75.0, "unit": "%"},
                {"property": "Tg", "predicted_value": -25.0, "unit": "°C"},
                {"property": "Volatile Matter", "predicted_value": 0.4, "unit": "%"},
            ],
            "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]}],
            "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
            "patent_references": ["US20250075019A1"],
        }
        # Candidate 2: boundary values
        cand_boundary = {
            "name": "Boundary Match Candidate",
            "compound": "7% carboxylated NBR",
            "predicted_properties": [
                {"property": "BACN", "predicted_value": 26.1, "unit": "%"},
                {"property": "Mooney (ML1+4 @ 100°C)", "predicted_value": 45.2, "unit": "MU"},
                {"property": "Stress Relaxation", "predicted_value": 0.102, "unit": ""},
                {"property": "pH", "predicted_value": 8.05, "unit": ""},
                {"property": "Total Solid Content", "predicted_value": 40.2, "unit": "%"},
                {"property": "Gel Content", "predicted_value": 70.5, "unit": "%"},
                {"property": "Tg", "predicted_value": -27.8, "unit": "°C"},
                {"property": "Volatile Matter", "predicted_value": 0.49, "unit": "%"},
            ],
            "stages": [{"stage_name": "Reactor Charge", "parameters": [{"name": "Water", "value": 180, "unit": "phr"}]}],
            "process_conditions": {"reaction_time": {"value": 8, "unit": "h"}},
            "patent_references": ["US20250075019A1"],
        }

        t_perf, _, _ = TargetValidationService.evaluate_recipe(cand_perfect, normalized, {})
        t_bound, _, _ = TargetValidationService.evaluate_recipe(cand_boundary, normalized, {})
        cand_perfect["target_analysis"] = t_perf
        cand_boundary["target_analysis"] = t_bound

        assert t_perf["targets_met"] == 8
        assert t_bound["targets_met"] == 8
        assert t_perf["target_margin_score"] > t_bound["target_margin_score"], (
            f"Target-centered candidate margin ({t_perf['target_margin_score']}) "
            f"MUST be strictly greater than boundary candidate margin ({t_bound['target_margin_score']})"
        )

        ranked = TargetValidationService.rank_candidates([cand_boundary, cand_perfect], normalized)
        assert ranked[0]["name"] == "Perfect Match Candidate", "Candidate matching target must rank #1"
        print("[SUCCESS] Target priority over Range verified mathematically and in candidate ranking!")

        # Create cycle and verify database cycle model
        cycle = RecipeCycle(
            compound_name="7% carboxylated NBR",
            created_by=user_id,
            status=RecipeCycleStatus.PENDING,
            target_properties=target_props,
            report_metadata_id=report_id,
        )
        session.add(cycle)
        await session.commit()
        await session.refresh(cycle)
        print(f"[SUCCESS] Cycle created: {cycle.id} with status={cycle.status}")
        assert len(cycle.target_properties) == 8, "All 8 properties must survive database persistence"

        print("[SUCCESS] All E2E validations passed cleanly!")

if __name__ == "__main__":
    asyncio.run(main())
