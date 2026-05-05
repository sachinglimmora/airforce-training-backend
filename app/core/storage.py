import json
import uuid

from minio import Minio
from minio.error import S3Error

from app.config import get_settings

settings = get_settings()

# Initialize the MinIO client
minio_client = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY or "minioadmin",
    secret_key=settings.MINIO_SECRET_KEY or "minioadmin",
    secure=settings.MINIO_SECURE,
)


def ensure_bucket_exists(bucket_name: str):
    try:
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)

        # Set bucket policy to public read
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
                }
            ],
        }
        minio_client.set_bucket_policy(bucket_name, json.dumps(policy))
    except S3Error as e:
        print(f"Error checking/creating bucket {bucket_name}: {e}")


# Ensure buckets exist and are public
ensure_bucket_exists(settings.MINIO_BUCKET_ASSETS)
ensure_bucket_exists(settings.MINIO_BUCKET_CONTENT)
ensure_bucket_exists("instructor-videos")


def upload_file_to_minio(file_obj, filename: str, content_type: str, bucket_name: str) -> str:
    """Uploads a file to MinIO and returns the public URL"""
    # Generate unique filename to prevent overwriting
    ext = filename.split(".")[-1] if "." in filename else ""
    unique_filename = f"{uuid.uuid4()}.{ext}" if ext else f"{uuid.uuid4()}"

    # Upload the file stream
    # length=-1 means the object length is unknown, so it uses multipart upload
    # part_size=10*1024*1024 is 10MB chunks
    minio_client.put_object(
        bucket_name,
        unique_filename,
        file_obj,
        length=-1,
        part_size=10 * 1024 * 1024,
        content_type=content_type,
    )

    # Construct and return the public URL
    protocol = "https" if settings.MINIO_SECURE else "http"
    return f"{protocol}://{settings.MINIO_ENDPOINT}/{bucket_name}/{unique_filename}"
