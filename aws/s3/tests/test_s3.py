import io
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.config import Config
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from s3files import S3Error, S3Files, content_disposition, normalize_key

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


def test_object_key_joins_prefix_folder_and_key():
    store = S3Files(_client(), "docs", prefix="/prod/")

    assert store.object_key("c1/f1", folder="Smlouvy/2026") == "prod/Smlouvy/2026/c1/f1"
    assert store.object_key("c1/f1") == "prod/c1/f1"


def test_put_returns_the_object_key_as_ref(files):
    store, stub = files
    stub.add_response(
        "put_object",
        {"ETag": '"abc"'},
        {
            "Bucket": "docs",
            "Key": "firma-1/Smlouvy/c1/f1",
            "Body": ANY,
            "ContentType": "application/pdf",
            "Metadata": {"name": "smlouva%20%C4%8D.%201.pdf"},
        },
    )

    info = store.put(
        "c1/f1", b"%PDF", "application/pdf", name="smlouva č. 1.pdf", folder="Smlouvy"
    )

    assert (info.key, info.size, info.etag) == ("firma-1/Smlouvy/c1/f1", 4, "abc")


def test_get_by_ref_does_not_add_the_prefix_again(files):
    store, stub = files
    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"hello"), 5), "ContentType": "text/plain"},
        {"Bucket": "docs", "Key": "firma-1/c1/f1"},
    )

    info, data = store.get("firma-1/c1/f1")

    assert data == b"hello"
    assert info.key == "firma-1/c1/f1"


def test_get_missing_raises_file_not_found(files):
    store, stub = files
    stub.add_client_error(
        "get_object", service_error_code="NoSuchKey", http_status_code=404
    )

    with pytest.raises(FileNotFoundError):
        store.get("firma-1/missing")


def test_locate_and_delete(files):
    store, stub = files
    stub.add_response(
        "head_object",
        {"ContentLength": 3, "ContentType": "text/plain"},
        {"Bucket": "docs", "Key": "firma-1/c1/f1"},
    )
    assert store.locate("c1/f1").size == 3

    stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
    assert store.delete("firma-1/gone") is False

    stub.add_response("head_object", {"ContentLength": 3, "ContentType": "text/plain"})
    stub.add_response("delete_object", {}, {"Bucket": "docs", "Key": "firma-1/c1/f1"})
    assert store.delete("firma-1/c1/f1") is True


def test_check_explains_missing_bucket(files):
    store, stub = files
    stub.add_client_error("head_bucket", service_error_code="404", http_status_code=404)

    with pytest.raises(S3Error, match="bucket not found"):
        store.check()


def test_presigned_urls_are_signed_for_the_key():
    store = S3Files(_client(), "docs", prefix="firma-1")

    url, expires, ref = store.upload_url(
        "c1/f9", "video/mp4", folder="Videa", lifetime=timedelta(minutes=5), now=NOW
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert ref == "firma-1/Videa/c1/f9"
    assert parsed.path == "/docs/firma-1/Videa/c1/f9"
    assert query["X-Amz-Expires"] == ["300"]
    assert "content-type" in query["X-Amz-SignedHeaders"][0]
    assert expires == NOW + timedelta(minutes=5)

    url, _ = store.download_url(ref, filename="prezentace č. 1.mp4")
    disposition = parse_qs(urlparse(url).query)["response-content-disposition"][0]
    assert disposition == content_disposition("prezentace č. 1.mp4")


def test_content_disposition_has_ascii_fallback_and_utf8_name():
    assert content_disposition('smlouva "č. 1".pdf') == (
        "attachment; filename=\"smlouva . 1.pdf\"; filename*=UTF-8''smlouva%20%22%C4%8D.%201%22.pdf"
    )


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
