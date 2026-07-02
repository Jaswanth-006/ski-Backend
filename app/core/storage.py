"""S3-compatible object storage (Phase 0-F). MinIO locally, S3/R2 in prod.

Provisioned for generated files (Excel exports in Phase 4) and, later, audio uploads,
served via short-lived pre-signed URLs. Disabled unless OBJECT_STORAGE_* is configured.
"""

from __future__ import annotations

from typing import Any

import boto3

from app.core.config import settings


def get_s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint,
        aws_access_key_id=settings.object_storage_access_key,
        aws_secret_access_key=settings.object_storage_secret_key,
        region_name=settings.object_storage_region,
    )


def ensure_bucket(client: Any | None = None) -> None:
    client = client or get_s3_client()
    buckets = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    if settings.object_storage_bucket not in buckets:
        client.create_bucket(Bucket=settings.object_storage_bucket)


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    get_s3_client().put_object(
        Bucket=settings.object_storage_bucket, Key=key, Body=data, ContentType=content_type
    )


def presigned_get_url(key: str) -> str:
    url: str = get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.object_storage_bucket, "Key": key},
        ExpiresIn=settings.presign_ttl_seconds,
    )
    return url
