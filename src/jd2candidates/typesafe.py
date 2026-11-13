"""Minimal TypeSafe System One client (stdlib urllib). Retries 429 with 2s, 4s, 8s backoff."""
import json
import time
import urllib.error
import urllib.request

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
BACKOFF = (2, 4, 8)


class TypeSafeError(RuntimeError):
    pass


class HTTPStatus(Exception):
    def __init__(self, code: int, body: str = ""):
        super().__init__(f"HTTP {code}: {body[:200]}")
        self.code = code


def urllib_post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise HTTPStatus(e.code, e.read().decode(errors="replace")) from None


def system_one(state, questions: dict, api_key: str, post=urllib_post) -> dict:
    body = {"model": MODEL, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {api_key}"}
    for i, wait in enumerate((*BACKOFF, None)):
        try:
            return post(URL, body, headers)
        except HTTPStatus as e:
            if e.code != 429 or wait is None:
                raise TypeSafeError(str(e)) from None
            time.sleep(wait)
    raise TypeSafeError("unreachable")
