#!/usr/bin/env python3
"""End-to-end check against a running Clipper API.

Uploads a real video, waits for the pipeline to find moments, renders the best one and
downloads it. Uses only the standard library.

    python scripts/smoke_test.py --api https://your-api.example --video talk.mp4 --token <jwt>

Authentication, either:
  --token <jwt>        a Clerk session token. They last about a minute, so this suits
                       short videos only. In the browser console while signed in:
                       await window.Clerk.session.getToken()
  --clerk-user-id <id> with CLERK_SECRET_KEY in the environment. A fresh token is minted
                       whenever one is needed, so long videos work.

The video should contain clear speech, otherwise there is nothing to find. Exits 0 when
every step passes, 1 otherwise.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

PART_RETRIES = 3


class SmokeFailure(Exception):
    pass


class Api:
    def __init__(self, base_url, token=None, clerk_user_id=None, clerk_secret=None):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._clerk_user_id = clerk_user_id
        self._clerk_secret = clerk_secret
        self._session_id = None
        self._token_minted_at = 0.0

    # -- auth ---------------------------------------------------------------

    def token(self):
        if self._token and not self._clerk_user_id:
            return self._token
        if time.time() - self._token_minted_at > 45:
            self._token = self._mint_token()
            self._token_minted_at = time.time()
        return self._token

    def _clerk(self, path, body):
        request = urllib.request.Request(
            f"https://api.clerk.com/v1{path}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._clerk_secret}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def _mint_token(self):
        if not self._session_id:
            self._session_id = self._clerk("/sessions", {"user_id": self._clerk_user_id})["id"]
        return self._clerk(f"/sessions/{self._session_id}/tokens", {})["jwt"]

    # -- requests -----------------------------------------------------------

    def call(self, method, path, body=None, authed=True):
        headers = {"Content-Type": "application/json"}
        if authed:
            headers["Authorization"] = f"Bearer {self.token()}"
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            raise SmokeFailure(f"{method} {path} answered {error.code}: {detail}") from None
        except urllib.error.URLError as error:
            raise SmokeFailure(f"{method} {path} could not connect: {error.reason}") from None
        return json.loads(raw) if raw else None


def put(url, data, content_type=None):
    """PUT bytes to a presigned URL. Returns the ETag header."""
    headers = {"Content-Type": content_type} if content_type else {}
    request = urllib.request.Request(url, data=data, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        raise SmokeFailure(f"storage rejected the upload ({error.code})") from None


def step(message):
    print(f"\n== {message}", flush=True)


def upload(api, path):
    size = os.path.getsize(path)
    plan = api.call("POST", "/videos/init", {"filename": os.path.basename(path), "size": size})
    video_id = plan["video_id"]
    print(f"upload mode: {plan['mode']}, video id: {video_id}")

    parts = None
    if plan["mode"] == "single":
        with open(path, "rb") as f:
            put(plan["upload_url"], f.read())
    else:
        parts = []
        part_size = plan["part_size"]
        with open(path, "rb") as f:
            for number in range(1, plan["part_count"] + 1):
                chunk = f.read(part_size)
                for attempt in range(1, PART_RETRIES + 1):
                    url = api.call("POST", f"/videos/{video_id}/parts", {"part_numbers": [number]})["urls"][str(number)]
                    try:
                        etag = put(url, chunk)
                        break
                    except SmokeFailure:
                        if attempt == PART_RETRIES:
                            raise
                if not etag:
                    raise SmokeFailure("storage did not return an ETag; check the bucket CORS ExposeHeaders")
                parts.append({"part_number": number, "etag": etag})
                print(f"  part {number}/{plan['part_count']} uploaded")

    api.call("POST", "/videos/complete", {"video_id": video_id, "parts": parts})
    return video_id


def wait_for_moments(api, video_id, timeout, interval):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        data = api.call("GET", f"/videos/{video_id}/moments")
        if data["status"] != last:
            print(f"  status: {data['status']}")
            last = data["status"]
        if data["status"] == "ready":
            return data
        if data["status"] == "error":
            raise SmokeFailure("the pipeline reported an error for this video")
        time.sleep(interval)
    raise SmokeFailure(f"video was not ready after {timeout}s (last status: {last})")


def wait_for_clip(api, clip_id, timeout, interval):
    deadline = time.time() + timeout
    while time.time() < deadline:
        clip = api.call("GET", f"/clips/{clip_id}")
        if clip["status"] == "ready":
            return clip
        if clip["status"] == "error":
            raise SmokeFailure("the render failed")
        time.sleep(interval)
    raise SmokeFailure(f"clip was not ready after {timeout}s")


def check_download(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        head = response.read(64)
    if b"ftyp" not in head:
        raise SmokeFailure("the downloaded file does not look like an mp4")


def run(args):
    secret = os.environ.get("CLERK_SECRET_KEY")
    if not args.token and not (args.clerk_user_id and secret):
        raise SmokeFailure("give --token, or --clerk-user-id together with CLERK_SECRET_KEY")
    api = Api(args.api, args.token, args.clerk_user_id, secret)

    step("API is reachable")
    api.call("GET", "/hit-it", authed=False)
    print("ok")

    step("Upload")
    video_id = upload(api, args.video)

    step("Waiting for transcription and moment detection")
    result = wait_for_moments(api, video_id, args.timeout, args.interval)
    moments = result["moments"]
    print(f"found {len(moments)} moments in {result.get('filename')}")
    for m in sorted(moments, key=lambda m: m["scores"].get("final", 0), reverse=True)[:5]:
        print(f"  {m['start_sec']:7.1f}s - {m['end_sec']:7.1f}s  score {m['scores'].get('final', 0):.2f}  {m['title']}")
    if not moments:
        raise SmokeFailure("no moments were found; use a video with clear speech")

    step("Rendering the best moment")
    best = max(moments, key=lambda m: m["scores"].get("final", 0))
    created = api.call("POST", "/clips/create", {
        "video_id": video_id,
        "start_sec": best["start_sec"],
        "end_sec": best["end_sec"],
        "format": args.format,
        "captions": True,
        "moment_id": best["id"],
    })
    clip = wait_for_clip(api, created["clip_id"], args.timeout, args.interval)
    check_download(clip["url"])
    print("downloaded a valid mp4")

    if args.cleanup:
        step("Cleaning up")
        api.call("DELETE", f"/videos/{video_id}")
        print("video deleted")

    print("\nSMOKE TEST PASSED")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", required=True, help="API base URL, e.g. http://localhost:8000")
    parser.add_argument("--video", required=True, help="path to a video with clear speech")
    parser.add_argument("--token", help="a Clerk session token")
    parser.add_argument("--clerk-user-id", help="mint tokens for this user (needs CLERK_SECRET_KEY)")
    parser.add_argument("--format", default="9:16", choices=["9:16", "1:1", "16:9", "original"])
    parser.add_argument("--timeout", type=int, default=1800, help="seconds to wait for each stage")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between status checks")
    parser.add_argument("--cleanup", action="store_true", help="delete the video afterwards")
    args = parser.parse_args(argv)
    try:
        run(args)
    except SmokeFailure as failure:
        print(f"\nSMOKE TEST FAILED: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
