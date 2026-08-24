"""
scripts/reset_dev_users.py

Explicit reset mechanism for development admin and user credentials.
Run this script manually to reset passwords to admin123 and user123.
"""
import asyncio
import sys
import os

# Add the parent directory to sys.path so we can import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.session import AsyncSessionLocal
from sqlalchemy import select
from app.models.user import User
from app.core.security import hash_password

async def reset_users():
    async with AsyncSessionLocal() as session:
        print("Resetting development admin/user credentials...")
        
        # Reset admin
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalar_one_or_none()
        if admin:
            admin.hashed_password = hash_password("admin123")
            print("Successfully reset admin password to 'admin123'.")
        else:
            print("Admin user not found. Did the app bootstrap yet?")
            
        # Reset user
        result = await session.execute(select(User).where(User.username == "user"))
        user = result.scalar_one_or_none()
        if user:
            user.hashed_password = hash_password("user123")
            print("Successfully reset user password to 'user123'.")
        else:
            print("Standard user not found.")
            
        await session.commit()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(reset_users())
