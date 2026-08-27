import asyncio
import json
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.future import select
from app.db.session import SessionLocal
from app.models.report_metadata import ReportMetadata

async def main():
    async with SessionLocal() as session:
        result = await session.execute(
            select(ReportMetadata).order_by(ReportMetadata.created_at.desc()).limit(1)
        )
        meta = result.scalars().first()
        if not meta:
            print("No reports found.")
            return
            
        print(f"Loaded ReportMetadata ID: {meta.id}")
        print(f"Run ID: {meta.research_run_id}")
        
        data = meta.structured_data
        if not data:
            print("structured_data is empty.")
            return
            
        print("\nTOP-LEVEL KEYS:")
        for key in data.keys():
            print(f"- {key}")
            
        if 'methodology_patents' in data:
            print(f"\nmethodology_patents length: {len(data['methodology_patents'])}")
        elif 'primary_patents' in data:
            print(f"\nprimary_patents length: {len(data['primary_patents'])}")
            
        # Let's inspect the first patent in the array
        patents = data.get('methodology_patents', data.get('primary_patents', []))
        if patents:
            print("\nFirst patent keys:")
            print(list(patents[0].keys()))
            if 'patent_details' in patents[0]:
                print("\npatent_details keys:")
                print(list(patents[0]['patent_details'].keys()))

if __name__ == "__main__":
    asyncio.run(main())
