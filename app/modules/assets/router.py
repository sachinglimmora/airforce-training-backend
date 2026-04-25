from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.assets.models import Asset
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.config import get_settings

router = APIRouter()
settings = get_settings()


def _presigned_url(storage_url: str) -> str:
    """Return a 15-min presigned GET URL for the given MinIO storage_url.

    storage_url is expected to be a MinIO object path of the form
    ``bucket/object/key``. Falls back to the raw URL if MinIO is not
    configured (e.g. local dev without credentials).
    """
    if not settings.MINIO_ACCESS_KEY or not settings.MINIO_SECRET_KEY:
        return storage_url

    try:
        from minio import Minio
        from datetime import timedelta

        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        # storage_url may be a full path like "aegis-assets/cockpit/b737.glb"
        # or a bare object key. Normalise to bucket + object_key.
        path = storage_url.lstrip("/")
        if "/" in path:
            bucket, object_key = path.split("/", 1)
        else:
            bucket = settings.MINIO_BUCKET_ASSETS
            object_key = path

        return client.presigned_get_object(
            bucket, object_key, expires=timedelta(seconds=900)
        )
    except Exception:
        return storage_url


@router.get("", summary="List assets (metadata only)")
async def list_assets(
    aircraft_id: str | None = Query(None),
    asset_type: str | None = Query(None),
    fidelity: str | None = Query(None),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    q = select(Asset)
    if aircraft_id:
        q = q.where(Asset.aircraft_id == aircraft_id)
    if asset_type:
        q = q.where(Asset.asset_type == asset_type)
    if fidelity:
        q = q.where(Asset.fidelity == fidelity)

    result = await db.execute(q)
    assets = result.scalars().all()
    return {
        "data": [
            {
                "id": str(a.id),
                "aircraft_id": str(a.aircraft_id) if a.aircraft_id else None,
                "asset_type": a.asset_type,
                "fidelity": a.fidelity,
                "format": a.format,
                "version": a.version,
                "file_size_bytes": a.file_size_bytes,
            }
            for a in assets
        ]
    }


@router.get("/{asset_id}", summary="Get asset metadata")
async def get_asset(
    asset_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        from app.core.exceptions import NotFound
        raise NotFound("Asset")
    return {
        "data": {
            "id": str(asset.id),
            "aircraft_id": str(asset.aircraft_id) if asset.aircraft_id else None,
            "asset_type": asset.asset_type,
            "fidelity": asset.fidelity,
            "format": asset.format,
            "version": asset.version,
            "checksum_sha256": asset.checksum_sha256,
        }
    }


@router.get("/{asset_id}/download", summary="Get presigned download URL (15-min expiry)")
async def download_asset(
    asset_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        from app.core.exceptions import NotFound
        raise NotFound("Asset")

    url = _presigned_url(asset.storage_url)
    return {
        "data": {
            "asset_id": asset_id,
            "download_url": url,
            "expires_in_seconds": 900,
            "format": asset.format,
        }
    }
