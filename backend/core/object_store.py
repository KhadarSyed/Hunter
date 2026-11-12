"""S3 storage for everything the platform keeps beyond the database: uploaded datasets, logos, icons, photos,
finished decks and the PPT reference decks, all under ROOT in AWS_S3_BUCKET. Optional: without the AWS_* keys every
call returns None and callers keep using Postgres. Failures are logged and return None, never raise."""
from __future__ import annotations

import functools
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = "HunterAgent/"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


@functools.lru_cache(maxsize=1)
def _client():
    """(boto3 client, bucket) or None when S3 is not configured."""
    bucket = _env("AWS_S3_BUCKET")
    if not (bucket and _env("AWS_ACCESS_KEY_ID") and _env("AWS_SECRET_ACCESS_KEY")):
        return None
    try:
        import boto3
        return boto3.client("s3", region_name=_env("AWS_REGION") or None, aws_access_key_id=_env("AWS_ACCESS_KEY_ID"),
                            aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY")), bucket
    except Exception as e:          # a bad region or missing boto3 means "no S3", never a crash
        logger.warning("S3 client not created: %s", type(e).__name__)
        return None


def enabled() -> bool:
    return _client() is not None


def _full(key: str) -> str:
    return key if key.startswith(ROOT) else ROOT + key.lstrip("/")


def put_bytes(key: str, data: bytes, content_type: str = "") -> str | None:
    c = _client()
    if c is None:
        return None
    s3, bucket = c
    try:
        s3.put_object(Bucket=bucket, Key=_full(key), Body=data,
                      **({"ContentType": content_type} if content_type else {}))
        return _full(key)
    except Exception as e:
        logger.warning("S3 put %s failed: %s", key[:120], type(e).__name__)
        return None


def get_bytes(key: str) -> bytes | None:
    c = _client()
    if c is None:
        return None
    s3, bucket = c
    try:
        return s3.get_object(Bucket=bucket, Key=_full(key))["Body"].read()
    except Exception as e:
        logger.info("S3 get %s failed: %s", key[:120], type(e).__name__)
        return None


def put_file(key: str, path: Path, content_type: str = "") -> str | None:
    c = _client()
    if c is None:
        return None
    s3, bucket = c
    try:
        s3.upload_file(str(path), bucket, _full(key),
                       ExtraArgs={"ContentType": content_type} if content_type else None)
        return _full(key)
    except Exception as e:
        logger.warning("S3 upload %s failed: %s", key[:120], type(e).__name__)
        return None


def download(key: str, out: Path) -> Path | None:
    c = _client()
    if c is None:
        return None
    s3, bucket = c
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(f".{out.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        s3.download_file(bucket, _full(key), str(part))
        os.replace(part, out)
        return out
    except Exception as e:
        logger.info("S3 download %s failed: %s", key[:120], type(e).__name__)
        part.unlink(missing_ok=True)
        return None


def delete(key: str) -> bool:
    c = _client()
    if c is None:
        return False
    s3, bucket = c
    try:
        s3.delete_object(Bucket=bucket, Key=_full(key))
        return True
    except Exception as e:
        logger.warning("S3 delete %s failed: %s", key[:120], type(e).__name__)
        return False


def list_keys(prefix: str) -> list[tuple[str, int]]:
    c = _client()
    if c is None:
        return []
    s3, bucket = c
    try:
        pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=_full(prefix))
        return [(o["Key"], o["Size"]) for p in pages for o in p.get("Contents", [])]
    except Exception as e:
        logger.warning("S3 list %s failed: %s", prefix[:120], type(e).__name__)
        return []
