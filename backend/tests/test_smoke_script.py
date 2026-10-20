"""scripts/smoke_test.py, run against a small fake of the Clipper API on localhost."""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_test.py"
spec = importlib.util.spec_from_file_location("smoke_test", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class FakeClipper:
    def __init__(self, multipart_part_size=None, moments=None, final_video_status="ready", clip_status="ready"):
        self.multipart_part_size = multipart_part_size
        self.moments = [{"id": "m1", "start_sec": 10.0, "end_sec": 40.0, "title": "Best bit", "scores": {"final": 0.9}}] if moments is None else moments
        self.final_video_status = final_video_status
        self.clip_status = clip_status
        self.requests = []
        self.stored = {}
        self.moment_polls = 0
        self.clip_polls = 0
        self.completed = None
        self.deleted = False


@pytest.fixture()
def server():
    state = FakeClipper()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, payload=None, status=200, headers=None, raw=None):
            body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else b"")
            self.send_response(status)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length)

        def _route(self, method):
            path = self.path
            base = f"http://127.0.0.1:{self.server.server_port}"
            data = self._body()
            state.requests.append((method, path))

            if path.startswith("/storage/"):
                if method == "PUT":
                    state.stored[path] = data
                    return self._send(headers={"ETag": f'"etag-{path.rsplit("/", 1)[-1]}"'})
                return self._send(raw=b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20)

            if path == "/hit-it":
                return self._send({"ok": True})

            if self.headers.get("Authorization") != "Bearer tok":
                return self._send({"detail": "Missing authorization header"}, status=401)

            body = json.loads(data) if data else {}
            if path == "/videos/init":
                if state.multipart_part_size:
                    count = -(-body["size"] // state.multipart_part_size)
                    return self._send({"mode": "multipart", "video_id": "v1", "upload_id": "u", "part_size": state.multipart_part_size, "part_count": count})
                return self._send({"mode": "single", "video_id": "v1", "upload_url": f"{base}/storage/single"})
            if path == "/videos/v1/parts":
                n = body["part_numbers"][0]
                return self._send({"urls": {str(n): f"{base}/storage/part/{n}"}})
            if path == "/videos/complete":
                state.completed = body
                return self._send({"video_id": "v1"})
            if path == "/videos/v1/moments":
                state.moment_polls += 1
                status = "processing" if state.moment_polls == 1 else state.final_video_status
                return self._send({"status": status, "filename": "talk.mp4", "moments": state.moments})
            if path == "/clips/create":
                state.created = body
                return self._send({"clip_id": "c1", "status": "queued"}, status=202)
            if path == "/clips/c1":
                state.clip_polls += 1
                if state.clip_polls == 1:
                    return self._send({"clip_id": "c1", "status": "rendering", "url": None})
                status = state.clip_status
                return self._send({"clip_id": "c1", "status": status, "url": f"{base}/storage/download" if status == "ready" else None})
            if path == "/videos/v1" and method == "DELETE":
                state.deleted = True
                return self._send({"video_id": "v1"})
            return self._send({"detail": "not found"}, status=404)

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_PUT(self):
            self._route("PUT")

        def do_DELETE(self):
            self._route("DELETE")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state.url = f"http://127.0.0.1:{httpd.server_port}"
    yield state
    httpd.shutdown()


def run(server, tmp_path, *extra, size=10, token="tok"):
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"x" * size)
    argv = ["--api", server.url, "--video", str(video), "--interval", "0", *extra]
    if token:
        argv += ["--token", token]
    return smoke.main(argv)


def test_single_upload_flow_passes(server, tmp_path, capsys):
    assert run(server, tmp_path) == 0
    out = capsys.readouterr().out
    assert "SMOKE TEST PASSED" in out and "Best bit" in out
    assert server.completed == {"video_id": "v1", "parts": None}
    assert server.stored["/storage/single"] == b"x" * 10
    assert server.created["moment_id"] == "m1" and server.created["format"] == "9:16"


def test_multipart_upload_sends_every_part_and_its_etag(server, tmp_path):
    server.multipart_part_size = 4
    assert run(server, tmp_path, size=10) == 0
    assert server.completed["parts"] == [
        {"part_number": 1, "etag": '"etag-1"'},
        {"part_number": 2, "etag": '"etag-2"'},
        {"part_number": 3, "etag": '"etag-3"'},
    ]
    assert [len(server.stored[f"/storage/part/{n}"]) for n in (1, 2, 3)] == [4, 4, 2]


def test_the_best_scoring_moment_is_rendered(server, tmp_path):
    server.moments = [
        {"id": "low", "start_sec": 1, "end_sec": 9, "title": "Meh", "scores": {"final": 0.2}},
        {"id": "high", "start_sec": 50, "end_sec": 80, "title": "Great", "scores": {"final": 0.95}},
    ]
    assert run(server, tmp_path, "--format", "1:1") == 0
    assert server.created["moment_id"] == "high" and server.created["start_sec"] == 50 and server.created["format"] == "1:1"


def test_cleanup_deletes_the_video(server, tmp_path):
    assert run(server, tmp_path, "--cleanup") == 0 and server.deleted is True


def test_no_cleanup_by_default(server, tmp_path):
    assert run(server, tmp_path) == 0 and server.deleted is False


def test_pipeline_error_fails_the_run(server, tmp_path, capsys):
    server.final_video_status = "error"
    assert run(server, tmp_path) == 1
    assert "SMOKE TEST FAILED" in capsys.readouterr().err


def test_no_moments_fails_the_run(server, tmp_path, capsys):
    server.moments = []
    assert run(server, tmp_path) == 1
    assert "no moments" in capsys.readouterr().err


def test_failed_render_fails_the_run(server, tmp_path, capsys):
    server.clip_status = "error"
    assert run(server, tmp_path) == 1
    assert "render failed" in capsys.readouterr().err


def test_timeout_fails_the_run(server, tmp_path, capsys):
    server.final_video_status = "processing"
    assert run(server, tmp_path, "--timeout", "0") == 1
    assert "not ready" in capsys.readouterr().err


def test_bad_token_is_reported_with_the_servers_message(server, tmp_path, capsys):
    assert run(server, tmp_path, token="wrong") == 1
    err = capsys.readouterr().err
    assert "401" in err and "Missing authorization header" in err


def test_missing_credentials_are_explained(server, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    assert run(server, tmp_path, token=None) == 1
    assert "--token" in capsys.readouterr().err


def test_unreachable_api_is_reported(tmp_path, capsys):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    assert smoke.main(["--api", "http://127.0.0.1:9", "--video", str(video), "--token", "t"]) == 1
    assert "could not connect" in capsys.readouterr().err
