"""Vector search + MMR + threshold filter. See spec §9."""


async def retrieve(db, query: str, aircraft_id, cfg) -> list:
    raise NotImplementedError
