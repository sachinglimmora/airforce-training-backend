from fastapi import APIRouter

router = APIRouter()

@router.get("", response_model=dict)
async def list_knowledge_entries():
    return {
        "data": [
            {
                "id": "1",
                "title": "Jet Engine Maintenance Fundamentals",
                "category": "Maintenance",
                "content": "Basic overview of jet engine maintenance procedures.",
                "tags": ["engine", "maintenance"]
            },
            {
                "id": "2",
                "title": "Avionics Safety Protocols",
                "category": "Safety",
                "content": "Safety guidelines for working with high-voltage avionics systems.",
                "tags": ["avionics", "safety"]
            }
        ]
    }
