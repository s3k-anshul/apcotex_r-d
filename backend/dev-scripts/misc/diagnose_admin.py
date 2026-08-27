import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.db.session import async_session_factory
from sqlalchemy import select
from app.models.user import User

async def diagnose_admin():
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()
        
        if not user:
            print("ADMIN AUTH DIAGNOSTIC:\nuser_found: false")
            return
            
        print("ADMIN AUTH DIAGNOSTIC:")
        print(f"user_found: true")
        print(f"active: {user.is_active}")
        print(f"role: {user.role.value}")
        print(f"password_hash_present: {bool(user.hashed_password)}")
        
        is_valid_format = False
        if user.hashed_password:
            if user.hashed_password.startswith("$2") or user.hashed_password.startswith("$argon2"):
                is_valid_format = True
                
        print(f"password_hash_valid: {is_valid_format}")

if __name__ == "__main__":
    asyncio.run(diagnose_admin())
