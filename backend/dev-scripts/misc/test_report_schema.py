"""
Test report schema validation with partial disclosure.
Verifies that the report schema accepts patents with optional fields.
"""
from app.services.pipeline.schemas import PatentResearchReport, ReportPatent, ReportPatentDetails, ReportPatentMethodology

def test_report_schema_partial_disclosure():
    print("=" * 60)
    print("TEST: Report Schema with Partial Disclosure")
    print("=" * 60)
    
    # Test 1: Minimal valid report (all optional fields)
    print("\n1. Minimal Report (all optional fields):")
    try:
        minimal_report = PatentResearchReport(
            title="Test Report",
            abstract="Test abstract",
            methodology_patents=[
                ReportPatent(
                    patent_details=ReportPatentDetails(
                        patent_number="US1234567",
                        patent_title="Test Patent",
                        assignee=None,  # Optional
                        jurisdiction=None,  # Optional
                        publication_year=None,  # Optional
                        polymer_type=None,  # Optional
                        relevance_to_target="Test relevance"
                    ),
                    polymerization_method=ReportPatentMethodology(
                        polymerization_process=None,  # Optional
                        monomer_system=None,  # Optional
                        monomer_ratio=None,  # Optional
                        water_amount=None,  # Optional
                        emulsifier=None,  # Optional
                        emulsifier_loading=None,  # Optional
                        initiator=None,  # Optional
                        initiator_loading=None,  # Optional
                        catalyst_activator=None,  # Optional
                        chain_transfer_agent=None,  # Optional
                        chain_transfer_dosage=None,  # Optional
                        polymerization_temperature=None,  # Optional
                        pressure=None,  # Optional
                        ph=None,  # Optional
                        reaction_time=None,  # Optional
                        conversion=None,  # Optional
                        coagulation_conditions=None,  # Optional
                        post_treatment=None,  # Optional
                        raw_polymer_properties=None  # Optional
                    ),
                    experimental_evidence=[],  # Optional
                    technical_relevance="Test technical relevance"
                )
            ],
            cross_patent_comparison=[],  # Optional
            references=[]  # Optional
        )
        print("   ✓ SUCCESS: Minimal report validated")
        print(f"   Patent details assignee: {minimal_report.methodology_patents[0].patent_details.assignee}")
        print(f"   Polymerization process: {minimal_report.methodology_patents[0].polymerization_method.polymerization_process}")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        return False
    
    # Test 2: Partial disclosure (some fields present)
    print("\n2. Partial Disclosure (some fields present):")
    try:
        partial_report = PatentResearchReport(
            title="Test Report",
            abstract="Test abstract",
            methodology_patents=[
                ReportPatent(
                    patent_details=ReportPatentDetails(
                        patent_number="US1234567",
                        patent_title="Test Patent",
                        assignee="Test Company",  # Present
                        jurisdiction="US",  # Present
                        publication_year=None,  # Missing
                        polymer_type="NBR",  # Present
                        relevance_to_target="Test relevance"
                    ),
                    polymerization_method=ReportPatentMethodology(
                        polymerization_process="Emulsion polymerization",  # Present
                        monomer_system="Butadiene/Acrylonitrile",  # Present
                        monomer_ratio=None,  # Missing
                        water_amount="200 parts",  # Present
                        emulsifier=None,  # Missing
                        emulsifier_loading=None,  # Missing
                        initiator="Potassium persulfate",  # Present
                        initiator_loading="2 parts",  # Present
                        catalyst_activator=None,  # Missing
                        chain_transfer_agent=None,  # Missing
                        chain_transfer_dosage=None,  # Missing
                        polymerization_temperature="50°C",  # Present
                        pressure=None,  # Missing
                        ph=None,  # Missing
                        reaction_time="8 hours",  # Present
                        conversion="80%",  # Present
                        coagulation_conditions=None,  # Missing
                        post_treatment=None,  # Missing
                        raw_polymer_properties=None  # Missing
                    ),
                    experimental_evidence=["Example 1: 100 parts butadiene, 12 parts acrylonitrile"],
                    technical_relevance="Test technical relevance"
                )
            ],
            cross_patent_comparison=["Comparison point 1"],
            references=["http://patents.google.com/patent/US1234567"]
        )
        print("   ✓ SUCCESS: Partial disclosure validated")
        print(f"   Assignee: {partial_report.methodology_patents[0].patent_details.assignee}")
        print(f"   Polymerization process: {partial_report.methodology_patents[0].polymerization_method.polymerization_process}")
        print(f"   Monomer system: {partial_report.methodology_patents[0].polymerization_method.monomer_system}")
        print(f"   Missing fields (None): polymer_type={partial_report.methodology_patents[0].patent_details.polymer_type}")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        return False
    
    # Test 3: Full disclosure (all fields present)
    print("\n3. Full Disclosure (all fields present):")
    try:
        full_report = PatentResearchReport(
            title="Test Report",
            abstract="Test abstract",
            methodology_patents=[
                ReportPatent(
                    patent_details=ReportPatentDetails(
                        patent_number="US1234567",
                        patent_title="Test Patent",
                        assignee="Test Company",
                        jurisdiction="US",
                        publication_year="2020",
                        polymer_type="NBR",
                        relevance_to_target="Test relevance"
                    ),
                    polymerization_method=ReportPatentMethodology(
                        polymerization_process="Emulsion polymerization",
                        monomer_system="Butadiene/Acrylonitrile",
                        monomer_ratio="88:12",
                        water_amount="200 parts",
                        emulsifier="Sodium dodecyl sulfate",
                        emulsifier_loading="1 part",
                        initiator="Potassium persulfate",
                        initiator_loading="2 parts",
                        catalyst_activator="None",
                        chain_transfer_agent="Tert-dodecyl mercaptan",
                        chain_transfer_dosage="0.5 parts",
                        polymerization_temperature="50°C",
                        pressure="Atmospheric",
                        ph="7.0",
                        reaction_time="8 hours",
                        conversion="80%",
                        coagulation_conditions="Aluminum sulfate solution",
                        post_treatment="Washing and drying",
                        raw_polymer_properties="Solid content 30%, Mooney viscosity 50"
                    ),
                    experimental_evidence=["Example 1 details", "Example 2 details"],
                    technical_relevance="Test technical relevance"
                )
            ],
            cross_patent_comparison=["Comparison point 1", "Comparison point 2"],
            references=["http://patents.google.com/patent/US1234567"]
        )
        print("   ✓ SUCCESS: Full disclosure validated")
        print(f"   All fields present and validated")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE: All schema variations validated")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = test_report_schema_partial_disclosure()
    if not success:
        exit(1)
