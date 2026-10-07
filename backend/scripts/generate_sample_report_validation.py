"""
backend/scripts/generate_sample_report_validation.py

Generates a fresh test report with structured tables, dynamic properties,
and cross-patent comparison to inspect both PDF and DOCX exports.
"""
import asyncio
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.pipeline.schemas import (
    PatentResearchReport,
    ReportPatent,
    ReportPatentDetails,
    ReportPatentMethodology,
    ExtractedTableSchema,
    MediumAndWaterRoleEvidence,
    DynamicTargetAttributeEvidence,
    ReportComparisonDimension,
)
from app.services.pipeline.report_service import ReportService, _build_dynamic_comparison_dimensions


async def main():
    service = ReportService()
    export_dir = os.path.abspath("exports")
    os.makedirs(export_dir, exist_ok=True)
    service.export_dir = export_dir

    p1 = ReportPatent(
        patent_details=ReportPatentDetails(
            patent_number="EP2473281B1",
            patent_title="Process for the Production of Nitrile Rubbers with Low Acrylonitrile Content",
            assignee="Arlanxeo Deutschland GmbH",
            jurisdiction="EP",
            publication_year="2016",
            priority_date="2010-12-15",
            legal_status="Active",
            polymer_type="Acrylonitrile-Butadiene Copolymer",
            relevance_to_target="Discloses direct aqueous emulsion polymerization of NBR with 20 wt% bound acrylonitrile.",
            relevance_tier="PRIMARY",
        ),
        polymerization_method=ReportPatentMethodology(
            dynamic_parameters=[
                "Synthesis method: Low-temperature aqueous cold emulsion polymerization in a continuous stirred-tank reactor cascade.",
                "Polymerization Temperature: 10 °C — Example 1",
                "Monomer Ratio / Composition: 21 wt% Acrylonitrile, 79 wt% 1,3-Butadiene — Initial Feed",
                "Initiator / Catalyst: Potassium persulfate / sodium bisulfite redox system — 0.25 phr",
                "Chain Transfer Agent: tert-Dodecyl mercaptan (t-DDM) — 0.35 phr",
                "Conversion: 75% at short-stop point — Example 1",
                "Reaction Time: 8.5 hours",
                "Mooney Viscosity: 45 ML(1+4) at 100 °C — Example 1",
                "Emulsifier / Surfactant: Sodium salt of disproportionated abietic acid — 2.5 phr",
                "Coagulant: Calcium chloride solution (2 wt%)",
            ]
        ),
        medium_and_water_role=MediumAndWaterRoleEvidence(
            core_reaction_medium="Aqueous emulsion",
            water_present=True,
            water_roles=["polymerization_medium", "latex", "washing"],
            summary="Aqueous emulsion serves as the primary polymerization medium, followed by steam stripping and aqueous salt coagulation.",
            evidence=["Polymerization carried out in demineralized water at 10 degrees C.", "Latex coagulated with calcium chloride."],
        ),
        target_attribute=DynamicTargetAttributeEvidence(
            label="Acrylonitrile Content",
            value="19.8 wt% bound acrylonitrile",
            status="direct",
            material_context="Cold polymerized NBR copolymer embodiment",
            belongs_to_target=True,
            evidence=["Example 1 yields copolymer having 19.8 wt% bound ACN."],
        ),
        tables=[
            ExtractedTableSchema(
                title="Table 1: Polymerization Feed & Latex Properties",
                headers=["Run", "Feed ACN (wt%)", "Polymerization Temp (°C)", "Conversion (%)", "Bound ACN (wt%)", "Mooney ML(1+4)"],
                rows=[
                    ["Example 1", "21.0", "10", "75", "19.8", "45"],
                    ["Example 2", "22.5", "10", "78", "21.2", "48"],
                    ["Comp. Ex. 1", "34.0", "10", "70", "33.5", "52"],
                ],
            )
        ],
        experimental_evidence=[
            "Example 1: Continuous cold emulsion polymerization at 10 °C yielding 19.8 wt% bound acrylonitrile at 75% conversion.",
            "Example 2: Feed adjusted to 22.5 wt% ACN yielding 21.2 wt% bound ACN with Mooney viscosity 48 ML(1+4).",
            "Comparative Example 1: Standard high-nitrile reference feed demonstrating shift in Mooney and glass transition.",
        ],
        technical_relevance="Direct technical match for targeted low-acrylonitrile cold emulsion NBR rubber with demonstrated molecular weight control.",
    )

    p2 = ReportPatent(
        patent_details=ReportPatentDetails(
            patent_number="US8530588B2",
            patent_title="Method for Producing Low-Temperature Resistant Nitrile Rubber",
            assignee="Zeon Corporation",
            jurisdiction="US",
            publication_year="2013",
            priority_date="2008-04-22",
            legal_status="Active",
            polymer_type="NBR",
            relevance_to_target="Describes low glass transition temperature NBR with 18-22% bound acrylonitrile prepared via emulsion.",
            relevance_tier="PRIMARY",
        ),
        polymerization_method=ReportPatentMethodology(
            dynamic_parameters=[
                "Synthesis method: Semi-batch emulsion copolymerization with staged monomer addition.",
                "Polymerization Temperature: 8 °C — Example 1",
                "Monomer Ratio / Composition: 20 wt% Acrylonitrile, 80 wt% 1,3-Butadiene",
                "Initiator / Catalyst: p-Menthane hydroperoxide / sodium formaldehyde sulfoxylate",
                "Chain Transfer Agent: tert-Dodecyl mercaptan — 0.40 phr",
                "Conversion: 80% — Example 1",
                "Reaction Time: 9.0 hours",
                "Mooney Viscosity: 42 ML(1+4) at 100 °C",
                "Emulsifier / Surfactant: Potassium oleate — 2.2 phr",
            ]
        ),
        medium_and_water_role=MediumAndWaterRoleEvidence(
            core_reaction_medium="Aqueous emulsion",
            water_present=True,
            water_roles=["polymerization_medium", "washing"],
            summary="Polymerization occurs in aqueous phase; water is subsequently removed during coagulated crumb isolation.",
            evidence=["Emulsion polymerization in water at 8 degrees C."],
        ),
        target_attribute=DynamicTargetAttributeEvidence(
            label="Acrylonitrile Content",
            value="20.4 wt%",
            status="direct",
            material_context="Low-temperature grade NBR rubber",
            belongs_to_target=True,
            evidence=["Copolymer contains 20.4 wt% bound acrylonitrile."],
        ),
        tables=[
            ExtractedTableSchema(
                title="Table 2: Vulcanizate Physical Properties",
                headers=["Sample", "Tensile Strength (MPa)", "Elongation at Break (%)", "Hardness (Shore A)", "Glass Transition Tg (°C)"],
                rows=[
                    ["Example 1", "24.5", "520", "65", "-38.5"],
                    ["Example 2", "26.0", "480", "68", "-36.0"],
                ],
            )
        ],
        experimental_evidence=[
            "Example 1: Demonstrates low Tg (-38.5 °C) elastomer vulcanizate with excellent tensile strength (24.5 MPa).",
            "Example 2: Formulated with secondary plasticizer for extreme low-temperature flexibility.",
        ],
        technical_relevance="Confirms mechanical properties, curing behavior, and low-temperature flexibility for ~20% ACN copolymer.",
    )

    p3 = ReportPatent(
        patent_details=ReportPatentDetails(
            patent_number="JP5689124B2",
            patent_title="Process for Preparing Nitrile Copolymer Latex",
            assignee="JSR Corporation",
            jurisdiction="JP",
            publication_year="2015",
            priority_date="2011-09-10",
            legal_status="Active",
            polymer_type="Carboxylated / Modified NBR Latex",
            relevance_to_target="Discloses low-ACN latex stabilization and coagulation procedure.",
            relevance_tier="PRIMARY",
        ),
        polymerization_method=ReportPatentMethodology(
            dynamic_parameters=[
                "Synthesis method: Emulsion polymerization with carboxylated modifier.",
                "Polymerization Temperature: 12 °C — Example 1",
                "Monomer Ratio / Composition: 21 wt% Acrylonitrile, 77 wt% Butadiene, 2 wt% Methacrylic acid",
                "Initiator / Catalyst: Diisopropylbenzene hydroperoxide",
                "Chain Transfer Agent: t-DDM — 0.30 phr",
                "Conversion: 82%",
                "Reaction Time: 7.5 hours",
                "Solids Content: 42 wt% in final latex",
            ]
        ),
        medium_and_water_role=MediumAndWaterRoleEvidence(
            core_reaction_medium="Aqueous emulsion",
            water_present=True,
            water_roles=["polymerization_medium", "latex"],
            summary="Emulsion polymerization in water; latex stabilized for dipping and coating applications.",
            evidence=["Aqueous polymerization medium with 42% final solids."],
        ),
        target_attribute=DynamicTargetAttributeEvidence(
            label="Acrylonitrile Content",
            value="21.0 wt%",
            status="direct",
            material_context="Carboxylated latex variant",
            belongs_to_target=True,
            evidence=["Latex polymer composition analyzed at 21 wt% ACN."],
        ),
        tables=[],
        experimental_evidence=[
            "Example 1: Stable latex with 42 wt% total solids and mean particle diameter 120 nm.",
        ],
        technical_relevance="Provides insight into carboxylated termonomer tolerance and latex stability for low-ACN emulsions.",
    )

    patents = [p1, p2, p3]

    # Build dynamic comparison dimensions
    medium_vals = {p.patent_details.patent_number: p.medium_and_water_role.summary for p in patents}
    target_vals = {p.patent_details.patent_number: p.target_attribute.value for p in patents}
    comparison_dimensions = _build_dynamic_comparison_dimensions(
        methodology_patents=patents,
        resolved_label="Acrylonitrile Content",
        medium_values=medium_vals,
        attribute_values=target_vals,
    )

    report = PatentResearchReport(
        title="PATENT RESEARCH REPORT: 20% ACRYLONITRILE NBR POLYMERIZATION",
        abstract=(
            "This research report reviews patent literature concerning the synthesis of low-acrylonitrile "
            "(approximately 20 wt%) acrylonitrile-butadiene rubber (NBR). Across the three identified primary "
            "patents (EP2473281B1, US8530588B2, JP5689124B2), cold aqueous emulsion polymerization operated between "
            "8 °C and 12 °C is the dominant commercial route. Radical redox initiation systems (KPS or organic hydroperoxides) "
            "combined with tertiary dodecyl mercaptan chain-transfer agents provide precise control of molecular weight and "
            "Mooney viscosity (42–48 ML). Target bound acrylonitrile contents of 19.8–21.0 wt% are consistently achieved."
        ),
        methodology_patents=patents,
        cross_patent_comparison=[
            "Polymerization Method: All primary patents utilize cold aqueous emulsion polymerization between 8 °C and 12 °C.",
            "Monomer Feed & Incorporation: Monomer charge ratios of 20–22.5 wt% ACN yield 19.8–21.2 wt% bound ACN in the polymer.",
            "Molecular Weight Control: tert-Dodecyl mercaptan (0.30–0.40 phr) is universally utilized as the chain-transfer agent.",
            "Conversion Levels: Polymerizations are short-stopped between 75% and 82% conversion to prevent excessive branching and gel formation.",
            "Downstream Workup: Unreacted monomers are recovered via steam stripping; latex is coagulated with calcium chloride or acid.",
        ],
        conclusion=(
            "The synthesis of 20% acrylonitrile NBR is thoroughly established in patent literature via cold emulsion "
            "polymerization. Key operational parameters include strict temperature maintenance at 8–12 °C, initiator "
            "feed control, and short-stopping at 75–80% conversion. Mechanical properties exhibit excellent low-temperature "
            "resistance with glass transition temperatures below -36 °C."
        ),
        references=[
            "EP2473281B1 | Process for the Production of Nitrile Rubbers | Arlanxeo Deutschland GmbH | EP | 2016 | https://patents.google.com/patent/EP2473281B1/en",
            "US8530588B2 | Method for Producing Low-Temperature Resistant Nitrile Rubber | Zeon Corporation | US | 2013 | https://patents.google.com/patent/US8530588B2/en",
            "JP5689124B2 | Process for Preparing Nitrile Copolymer Latex | JSR Corporation | JP | 2015 | https://patents.google.com/patent/JP5689124B2/en",
        ],
        dynamic_target_attribute_label="Acrylonitrile Content",
        comparison_dimensions=comparison_dimensions,
    )

    # 1. Export to Markdown
    markdown = service.report_to_markdown(report)
    md_path = os.path.join(export_dir, "validation_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"Markdown report generated: {md_path}")

    # 2. Export to PDF
    pdf_path = await service.export_to_pdf(markdown, "validation_report.pdf")
    print(f"PDF report generated: {pdf_path}")

    # 3. Export to DOCX
    docx_path = await service.export_to_docx(report, "validation_report.docx")
    print(f"DOCX report generated: {docx_path}")

    print("ALL REPORTS GENERATED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(main())
