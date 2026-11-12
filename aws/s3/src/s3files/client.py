"""S3 as a file store. Secret shape (the platform's connection secret)::

    {"bucket": "...", "region": "eu-central-1", "prefix": "optional/", "endpointUrl": "http://localhost:4566",
     "accessKeyId": "...", "secretAccessKey": "..."}

Keys are optional against real AWS (the Lambda's role is used); ``endpointUrl`` only for S3-compatible stores.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

DEFAULT_URL_LIFETIME = timedelta(minutes=15)


class S3Error(RuntimeError):
    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class S3File:
    key: str
    size: int
    content_type: str
    modified: datetime | None = None
    etag: str = ""


def normalize_key(key: str) -> str:
    parts = [p for p in str(key).replace("\\", "/").split("/") if p]
    if not parts or str(key).startswith("/") or any(p in (".", "..") for p in parts):
        raise ValueError(f"Invalid file key {key!r}.")
    return "/".join(parts)


def _pick(secret: Mapping[str, Any], *keys: str) -> str:
    lower = {str(k).lower(): v for k, v in secret.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


class S3Files:
    def __init__(self, client: Any, bucket: str, *, prefix: str = "") -> None:
        if not bucket:
            raise ValueError("S3 needs a bucket.")
        self.client = client
        self.bucket = bucket
        self.prefix = "/".join(p for p in prefix.replace("\\", "/").split("/") if p)

    @classmethod
    def from_secret(cls, secret: Mapping[str, Any]) -> S3Files:
        bucket = _pick(secret, "bucket", "bucketOrContainer")
        if not bucket:
            raise ValueError(
                "The S3 connection has no bucket. Add one in the connection settings."
            )
        endpoint = _pick(secret, "endpointUrl", "endpoint_url")
        kwargs: dict[str, Any] = {
            "region_name": _pick(secret, "region") or "eu-central-1",
            # Path style for S3-compatible endpoints (LocalStack, MinIO); virtual hosts for AWS.
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if endpoint else "auto"},
            ),
        }
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        access_key = _pick(secret, "accessKeyId", "access_key_id")
        secret_key = _pick(secret, "secretAccessKey", "secret_access_key")
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        return cls(boto3.client("s3", **kwargs), bucket, prefix=_pick(secret, "prefix"))

    def _key(self, key: str) -> str:
        normalized = normalize_key(key)
        return f"{self.prefix}/{normalized}" if self.prefix else normalized

    def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> S3File:
        full = self._key(key)
        try:
            response = self.client.put_object(
                Bucket=self.bucket, Key=full, Body=data, ContentType=content_type
            )
        except ClientError as exc:
            raise S3Error(f"S3 upload failed: {_code(exc) or exc}", _code(exc)) from exc
        return S3File(
            key=normalize_key(key),
            size=len(data),
            content_type=content_type,
            etag=str(response.get("ETag") or "").strip('"'),
        )

    def stat(self, key: str) -> S3File | None:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as exc:
            if _code(exc) in ("404", "NoSuchKey", "NotFound"):
                return None
            raise S3Error(f"S3 lookup failed: {_code(exc) or exc}", _code(exc)) from exc
        return S3File(
            key=normalize_key(key),
            size=int(head.get("ContentLength") or 0),
            content_type=str(head.get("ContentType") or "application/octet-stream"),
            modified=head.get("LastModified"),
            etag=str(head.get("ETag") or "").strip('"'),
        )

    def get(self, key: str) -> tuple[S3File, bytes]:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as exc:
            if _code(exc) in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"No S3 object at '{key}'.") from exc
            raise S3Error(
                f"S3 download failed: {_code(exc) or exc}", _code(exc)
            ) from exc
        data = obj["Body"].read()
        info = S3File(
            key=normalize_key(key),
            size=len(data),
            content_type=str(obj.get("ContentType") or "application/octet-stream"),
            modified=obj.get("LastModified"),
            etag=str(obj.get("ETag") or "").strip('"'),
        )
        return info, data

    def delete(self, key: str) -> bool:
        """True when there was an object to delete (S3 itself answers the same either way)."""
        if self.stat(key) is None:
            return False
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as exc:
            raise S3Error(f"S3 delete failed: {_code(exc) or exc}", _code(exc)) from exc
        return True

    def upload_url(
        self,
        key: str,
        content_type: str,
        *,
        lifetime: timedelta = DEFAULT_URL_LIFETIME,
        now: datetime | None = None,
    ) -> tuple[str, datetime]:
        """Presigned PUT the browser sends the bytes to (with the same Content-Type header)."""
        url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": self._key(key),
                "ContentType": content_type,
            },
            ExpiresIn=int(lifetime.total_seconds()),
        )
        return url, (now or datetime.now(UTC)) + lifetime

    def download_url(
        self,
        key: str,
        *,
        filename: str | None = None,
        lifetime: timedelta = DEFAULT_URL_LIFETIME,
        now: datetime | None = None,
    ) -> tuple[str, datetime]:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": self._key(key)}
        if filename:
            safe = filename.replace('"', "")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        url = self.client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=int(lifetime.total_seconds())
        )
        return url, (now or datetime.now(UTC)) + lifetime

    def check(self) -> str:
        """Raises S3Error with the reason when the bucket is unreachable; returns the bucket name otherwise."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = _code(exc)
            reason = {
                "403": "no permission for this bucket",
                "404": "bucket not found",
            }.get(code, code or str(exc))
            raise S3Error(f"S3 check failed: {reason}", code) from exc
        except BotoCoreError as exc:
            raise S3Error(f"S3 check failed: {exc}") from exc
        return self.bucket
