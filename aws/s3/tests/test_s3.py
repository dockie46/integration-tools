import io
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.config import Config
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from s3files import S3Error, S3Files, normalize_key

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def _client():
    return boto3.client(
        "s3",
        region_name="eu-central-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        endpoint_url="http://localhost:4566",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@pytest.fixture
def files():
    client = _client()
    with Stubber(client) as stub:
        yield S3Files(client, "docs", prefix="firma-1/"), stub


@pytest.mark.parametrize(
    ("key", "expected"),
    [("a/b/c.pdf", "a/b/c.pdf"), ("a//b\\c.pdf", "a/b/c.pdf"), ("x.txt", "x.txt")],
)
def test_normalize_key(key, expected):
    assert normalize_key(key) == expected


@pytest.mark.parametrize("key", ["", "/abs.pdf", "a/../b.pdf", "./x"])
def test_normalize_key_rejects(key):
    with pytest.raises(ValueError, match="Invalid file key"):
        normalize_key(key)


def test_put_uses_prefix_and_content_type(files):
    store, stub = files
    stub.add_response(
        "put_object",
        {"ETag": '"abc"'},
        {
            "Bucket": "docs",
            "Key": "firma-1/smlouvy/a.pdf",
            "Body": ANY,
            "ContentType": "application/pdf",
        },
    )

    info = store.put("smlouvy/a.pdf", b"%PDF", "application/pdf")

    assert (info.key, info.size, info.etag) == ("smlouvy/a.pdf", 4, "abc")


def test_get_returns_bytes(files):
    store, stub = files
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"hello"), 5), "ContentType": "text/plain"},
        {"Bucket": "docs", "Key": "firma-1/a.txt"},
    )

    info, data = store.get("a.txt")

    assert data == b"hello"
    assert info.content_type == "text/plain"


def test_get_missing_raises_file_not_found(files):
    store, stub = files
    stub.add_client_error(
        "get_object", service_error_code="NoSuchKey", http_status_code=404
    )

    with pytest.raises(FileNotFoundError):
        store.get("missing.txt")


def test_delete_reports_whether_it_existed(files):
    store, stub = files
    stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
    assert store.delete("gone.txt") is False

    stub.add_response("head_object", {"ContentLength": 3, "ContentType": "text/plain"})
    stub.add_response(
        "delete_object", {}, {"Bucket": "docs", "Key": "firma-1/here.txt"}
    )
    assert store.delete("here.txt") is True


def test_check_explains_missing_bucket(files):
    store, stub = files
    stub.add_client_error("head_bucket", service_error_code="404", http_status_code=404)

    with pytest.raises(S3Error, match="bucket not found"):
        store.check()


def test_presigned_urls_are_signed_for_the_key():
    store = S3Files(_client(), "docs", prefix="firma-1")

    url, expires = store.upload_url(
        "video/big.mp4", "video/mp4", lifetime=timedelta(minutes=5), now=NOW
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/docs/firma-1/video/big.mp4"
    assert query["X-Amz-Expires"] == ["300"]
    assert "content-type" in query["X-Amz-SignedHeaders"][0]
    assert expires == NOW + timedelta(minutes=5)

    url, _ = store.download_url("video/big.mp4", filename='big "1".mp4')
    assert "response-content-disposition" in urlparse(url).query


def test_from_secret_requires_bucket():
    with pytest.raises(ValueError, match="no bucket"):
        S3Files.from_secret({"region": "eu-central-1"})


def test_from_secret_accepts_platform_shape():
    store = S3Files.from_secret(
        {
            "bucketOrContainer": "docs",
            "endpointUrl": "http://localhost:4566",
            "accessKeyId": "test",
            "secretAccessKey": "test",
            "prefix": "/a/b/",
        }
    )

    assert (store.bucket, store.prefix) == ("docs", "a/b")
    assert store.client.meta.endpoint_url == "http://localhost:4566"
