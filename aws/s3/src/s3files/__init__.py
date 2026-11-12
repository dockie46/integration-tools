"""S3 (and S3-compatible: LocalStack, MinIO, R2, Wasabi) files for apps."""

from .client import S3Error, S3File, S3Files, content_disposition, normalize_key

__all__ = ["S3Error", "S3File", "S3Files", "content_disposition", "normalize_key"]

__version__ = "0.1.0"
