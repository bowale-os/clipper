"""Storage helpers, run against a real boto3 client whose HTTP layer is stubbed.

Stubber checks every call's parameters against the S3 API model, so a wrong argument
name or a missing field fails here instead of in production.
"""
import io
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from botocore.stub import Stubber

import app.services.r2_client as r2

BUCKET = "test-bucket"


@pytest.fixture()
def s3(monkeypatch):
    client = r2.get_r2_client()
    monkeypatch.setattr(r2, "get_r2_client", lambda: client)
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def test_client_targets_the_configured_endpoint():
    client = r2.get_r2_client()
    assert client.meta.endpoint_url == "https://r2.test.invalid"
    assert client.meta.region_name == "auto"


# ---------------------------------------------------------------- presigned URLs (signed locally)


def test_upload_url_is_signed_for_the_key_and_content_type():
    url = r2.generate_upload_url("sources/abc/original.mp4", "video/mp4")
    parsed = urlparse(url)
    assert parsed.netloc.endswith("r2.test.invalid")
    assert "sources/abc/original.mp4" in parsed.path
    query = parse_qs(parsed.query)
    assert query["X-Amz-Expires"] == ["3600"] and "X-Amz-Signature" in query


def test_download_url_honours_expiry():
    url = r2.generate_download_url("clips/a.mp4", expires_in=120)
    assert parse_qs(urlparse(url).query)["X-Amz-Expires"] == ["120"]


def test_part_urls_are_signed_per_part():
    urls = r2.generate_part_upload_urls("k.mp4", "upload-1", [2, 5])
    assert set(urls) == {2, 5}
    for number, url in urls.items():
        query = parse_qs(urlparse(url).query)
        assert query["partNumber"] == [str(number)] and query["uploadId"] == ["upload-1"]


# ---------------------------------------------------------------- objects


def test_upload_bytes_puts_the_object(s3):
    client, stub = s3
    stub.add_response(
        "put_object",
        {},
        {"Bucket": BUCKET, "Key": "a.json", "Body": b"{}", "ContentType": "application/json"},
    )
    r2.upload_bytes(b"{}", "a.json", "application/json")


def test_download_bytes_reads_the_body(s3):
    client, stub = s3
    from botocore.response import StreamingBody

    stub.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"hello"), 5)},
        {"Bucket": BUCKET, "Key": "a.json"},
    )
    assert r2.download_bytes("a.json") == b"hello"


def test_delete_file(s3):
    client, stub = s3
    stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": "a.mp4"})
    r2.delete_file("a.mp4")


def test_upload_and_download_file_delegate_to_the_transfer_api(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(r2, "get_r2_client", lambda: fake)
    r2.upload_file("/tmp/x.mp4", "clips/x.mp4")
    fake.upload_file.assert_called_once_with(Filename="/tmp/x.mp4", Bucket=BUCKET, Key="clips/x.mp4")
    r2.download_file("sources/a.mp4", "/tmp/a.mp4")
    fake.download_file.assert_called_once_with(Bucket=BUCKET, Key="sources/a.mp4", Filename="/tmp/a.mp4")


# ---------------------------------------------------------------- delete_prefix


def test_delete_prefix_removes_everything_across_pages(s3):
    client, stub = s3
    stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "p/1"}, {"Key": "p/2"}], "IsTruncated": True, "NextContinuationToken": "t"},
        {"Bucket": BUCKET, "Prefix": "p"},
    )
    stub.add_response("delete_objects", {}, {"Bucket": BUCKET, "Delete": {"Objects": [{"Key": "p/1"}, {"Key": "p/2"}]}})
    stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "p/3"}], "IsTruncated": False},
        {"Bucket": BUCKET, "Prefix": "p", "ContinuationToken": "t"},
    )
    stub.add_response("delete_objects", {}, {"Bucket": BUCKET, "Delete": {"Objects": [{"Key": "p/3"}]}})
    assert r2.delete_prefix("p") == 3


def test_delete_prefix_with_nothing_there(s3):
    client, stub = s3
    stub.add_response("list_objects_v2", {"IsTruncated": False}, {"Bucket": BUCKET, "Prefix": "empty"})
    assert r2.delete_prefix("empty") == 0


# ---------------------------------------------------------------- multipart


def test_create_multipart_upload_returns_the_upload_id(s3):
    client, stub = s3
    stub.add_response(
        "create_multipart_upload",
        {"UploadId": "up-1"},
        {"Bucket": BUCKET, "Key": "k", "ContentType": "video/mp4"},
    )
    assert r2.create_multipart_upload("k", "video/mp4") == "up-1"


def test_list_uploaded_parts_follows_pagination(s3):
    client, stub = s3
    stub.add_response(
        "list_parts",
        {"Parts": [{"PartNumber": 1, "ETag": '"a"', "Size": 5}], "IsTruncated": True, "NextPartNumberMarker": 1},
        {"Bucket": BUCKET, "Key": "k", "UploadId": "u", "PartNumberMarker": 0, "MaxParts": 1000},
    )
    stub.add_response(
        "list_parts",
        {"Parts": [{"PartNumber": 2, "ETag": '"b"', "Size": 6}], "IsTruncated": False},
        {"Bucket": BUCKET, "Key": "k", "UploadId": "u", "PartNumberMarker": 1, "MaxParts": 1000},
    )
    assert r2.list_uploaded_parts("k", "u") == [
        {"part_number": 1, "etag": '"a"', "size": 5},
        {"part_number": 2, "etag": '"b"', "size": 6},
    ]


def test_list_uploaded_parts_with_none_uploaded(s3):
    client, stub = s3
    stub.add_response(
        "list_parts", {"IsTruncated": False}, {"Bucket": BUCKET, "Key": "k", "UploadId": "u", "PartNumberMarker": 0, "MaxParts": 1000}
    )
    assert r2.list_uploaded_parts("k", "u") == []


def test_list_uploaded_parts_propagates_expired_uploads(s3):
    from botocore.exceptions import ClientError

    client, stub = s3
    stub.add_client_error("list_parts", service_error_code="NoSuchUpload")
    with pytest.raises(ClientError) as err:
        r2.list_uploaded_parts("k", "u")
    assert err.value.response["Error"]["Code"] == "NoSuchUpload"


def test_complete_multipart_sorts_parts_and_keeps_etags_verbatim(s3):
    client, stub = s3
    stub.add_response(
        "complete_multipart_upload",
        {},
        {
            "Bucket": BUCKET,
            "Key": "k",
            "UploadId": "u",
            "MultipartUpload": {"Parts": [{"PartNumber": 1, "ETag": '"a"'}, {"PartNumber": 2, "ETag": '"b"'}]},
        },
    )
    r2.complete_multipart_upload("k", "u", [{"part_number": 2, "etag": '"b"'}, {"part_number": 1, "etag": '"a"'}])


def test_abort_multipart_upload(s3):
    client, stub = s3
    stub.add_response("abort_multipart_upload", {}, {"Bucket": BUCKET, "Key": "k", "UploadId": "u"})
    r2.abort_multipart_upload("k", "u")


# ---------------------------------------------------------------- head_object_size


def test_head_object_size_returns_the_length(s3):
    client, stub = s3
    stub.add_response("head_object", {"ContentLength": 1234}, {"Bucket": BUCKET, "Key": "k"})
    assert r2.head_object_size("k") == 1234


def test_head_object_size_is_none_when_missing(s3):
    client, stub = s3
    stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
    assert r2.head_object_size("k") is None
