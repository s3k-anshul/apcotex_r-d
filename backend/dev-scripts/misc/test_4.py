import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import AsyncSessionLocal
from sqlalchemy import text
from app.models.search_result import SearchResult
import uuid
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    try:
        print("Running Test 4 - Database Rollback")
        async with AsyncSessionLocal() as session:
            # First, try to insert a valid dummy record
            test_run_id = uuid.uuid4()
            test_query_id = uuid.uuid4()
            
            # Since we have foreign keys, inserting directly into search_results without a run might fail.
            # Instead of a full insert, let's just trigger a manual syntax error to poison the transaction
            print("Intentionally causing a DB error...")
            try:
                await session.execute(text("SELECT * FROM non_existent_table"))
            except Exception as e:
                print(f"Caught expected DB error: {e}")
                print("Rolling back...")
                await session.rollback()
                
            # Now verify the session is still usable
            print("Verifying session is still alive...")
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
            if val == 1:
                print("TEST 4: PASS (Session recovered successfully after rollback)")
            else:
                print("TEST 4: FAIL (Session returned unexpected result)")
    except Exception as e:
        print(f"TEST 4: FAIL (Exception {e})")

if __name__ == "__main__":
    asyncio.run(main())
