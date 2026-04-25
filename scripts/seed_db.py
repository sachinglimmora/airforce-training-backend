"""Seed the database with Phase 1 baseline data.

Run with: python -m scripts.seed_db
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dotenv import load_dotenv

# Force load .env from current directory
load_dotenv()

from app.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import Permission, Role, RolePermission, User, UserRole
from app.modules.content.models import Aircraft

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL)
AsyncSession_ = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


ROLES = [
    ("trainee", "Pilot trainee — read content, execute checklist/procedure sessions"),
    ("instructor", "Instructor — manage trainees, run sessions, create scenarios"),
    ("evaluator", "Evaluator — submit and review evaluations"),
    ("admin", "Platform administrator — full access"),
]

AIRCRAFT = [
    ("B737-800", "Boeing", "Boeing 737-800"),
    ("A320", "Airbus", "Airbus A320"),
]

ADMIN_EMAIL = "admin@aegis.internal"
ADMIN_PASSWORD = "Aegis@Admin2026!"


async def seed():
    print(f"DEBUG: Using database URL: {settings.DATABASE_URL}")
    async with AsyncSession_() as db:
        async with db.begin():
            # Roles
            role_map: dict[str, Role] = {}
            for name, description in ROLES:
                from sqlalchemy import select
                existing = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
                if not existing:
                    role = Role(name=name, description=description)
                    db.add(role)
                    await db.flush()
                    role_map[name] = role
                else:
                    role_map[name] = existing

            # Aircraft
            for type_code, manufacturer, display_name in AIRCRAFT:
                from sqlalchemy import select
                existing = (await db.execute(select(Aircraft).where(Aircraft.type_code == type_code))).scalar_one_or_none()
                if not existing:
                    db.add(Aircraft(type_code=type_code, manufacturer=manufacturer, display_name=display_name))

            # Admin user
            from sqlalchemy import select
            existing_admin = (await db.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one_or_none()
            if not existing_admin:
                admin = User(
                    email=ADMIN_EMAIL,
                    full_name="Platform Admin",
                    password_hash=hash_password(ADMIN_PASSWORD),
                    employee_id="ADMIN-001",
                )
                db.add(admin)
                await db.flush()
                db.add(UserRole(user_id=admin.id, role_id=role_map["admin"].id))
                print(f"Created admin user: {ADMIN_EMAIL}")
            else:
                print("Admin user already exists — skipping")

    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
