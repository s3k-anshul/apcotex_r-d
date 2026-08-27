from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patent_document import PatentDocument

class PatentDocumentRepository:
    async def get_by_patent_number(self, session: AsyncSession, patent_number: str) -> PatentDocument | None:
        stmt = select(PatentDocument).where(PatentDocument.patent_number == patent_number)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_update(self, session: AsyncSession, patent_data: dict) -> PatentDocument:
        doc = await self.get_by_patent_number(session, patent_data["patent_number"])
        if not doc:
            doc = PatentDocument(**patent_data)
            session.add(doc)
        else:
            for key, value in patent_data.items():
                setattr(doc, key, value)
        
        await session.commit()
        await session.refresh(doc)
        return doc
