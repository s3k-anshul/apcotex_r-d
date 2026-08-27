import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.llm.llm_client import llm_client
from pydantic import BaseModel
import logging

logging.basicConfig(level=logging.INFO)

class TestSchema(BaseModel):
    status: str
    message: str

async def main():
    try:
        print("Running Test 1 - Provider Health")
        result, usage = await llm_client.generate_structured(
            prompt="Reply with status OK and message 'Hello world'",
            system_prompt="You are a test bot.",
            schema=TestSchema,
            temperature=0.1,
            metadata={"stage": "TEST_1", "patent": "N/A", "chunk": "1"}
        )
        print(f"\nResult: {result}")
        print(f"Usage: {usage}")
        if result and result.status == "OK":
            print("TEST 1: PASS")
        else:
            print("TEST 1: FAIL (Unexpected result)")
    except Exception as e:
        print(f"TEST 1: FAIL (Exception {e})")

if __name__ == "__main__":
    asyncio.run(main())
