import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.modules.training.models import Course, TrainingModule

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL)
AsyncSession_ = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

COURSES = [
    {
        "id": uuid.uuid4(),
        "title": "Jet Engine Systems",
        "description": "Comprehensive guide to modern jet turbine operation and maintenance.",
        "category": "Jet Engine Systems",
        "duration": "12 hours",
        "difficulty": "intermediate",
        "status": "in-progress",
        "module_count": 3,
        "completed_modules": 1,
        "progress": 33,
    },
    {
        "id": uuid.uuid4(),
        "title": "Avionics Fundamentals",
        "description": "Introduction to cockpit instrumentation and flight management systems.",
        "category": "Avionics",
        "duration": "8 hours",
        "difficulty": "beginner",
        "status": "not-started",
        "module_count": 2,
        "completed_modules": 0,
        "progress": 0,
    },
]

MODULES = [
    {
        "course_index": 0,
        "title": "Turbine Blade Inspection",
        "description": "Visual and borescope inspection procedures for high-pressure turbine blades.",
        "category": "Jet Engine Systems",
        "duration": "45 mins",
        "order": 1,
        "is_completed": True,
    },
    {
        "course_index": 0,
        "title": "Fuel Nozzle Maintenance",
        "description": "Removal and cleaning of fuel nozzles for consistent combustion.",
        "category": "Jet Engine Systems",
        "duration": "1 hour",
        "order": 2,
        "is_completed": False,
    },
    {
        "course_index": 1,
        "title": "Glass Cockpit Overview",
        "description": "Understanding Primary Flight Displays (PFD) and Multi-Function Displays (MFD).",
        "category": "Avionics",
        "duration": "30 mins",
        "order": 1,
        "is_completed": False,
    },
]


async def seed_training():
    async with AsyncSession_() as db:
        async with db.begin():
            # Create Courses
            course_objects = []
            for c_data in COURSES:
                course = Course(**c_data)
                db.add(course)
                course_objects.append(course)

            await db.flush()

            # Create Modules
            for m_data in MODULES:
                c_idx = m_data.pop("course_index")
                course_id = course_objects[c_idx].id
                module = TrainingModule(course_id=course_id, **m_data)
                db.add(module)

    print("Training data seeded.")


if __name__ == "__main__":
    asyncio.run(seed_training())
