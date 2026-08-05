"""Thin client for the Elexon Insights API.

No API key needed. Everything is cached to disk as raw JSON so a rerun costs
nothing and so the numbers in the note can be reproduced from the same files.
"""

import hashlib
import json
import time
from pathlib import Path

import requests

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
CACHE = Path(__file__).resolve().parents[1] / "data" / "raw"


class ElexonError(RuntimeError):
    pass


def _cache_path(path, params):
    key = json.dumps({"path": path, "params": params}, sort_keys=True)
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    safe = path.strip("/").replace("/", "_")
    return CACHE / f"{safe}_{digest}.json"


def get(path, params=None, use_cache=True, retries=4):
    """GET an endpoint and return the parsed body. Results are cached by path plus params."""
    params = params or {}
    cache_file = _cache_path(path, params)

    if use_cache and cache_file.exists():
        with open(cache_file) as fh:
            return json.load(fh)

    url = f"{BASE}{path}"
    last_error = None

    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            body = resp.json()
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w") as fh:
                json.dump(body, fh)
            return body

        # 429 and 5xx are worth another go, anything else is not
        if resp.status_code in (429, 500, 502, 503, 504):
            last_error = ElexonError(f"{resp.status_code} from {url}")
            time.sleep(2 ** attempt)
            continue

        raise ElexonError(f"{resp.status_code} from {url}: {resp.text[:200]}")

    raise ElexonError(f"gave up on {url}: {last_error}")


def rows(path, params=None, use_cache=True):
    """Same as get() but returns the data list, which is what almost every endpoint wraps."""
    body = get(path, params=params, use_cache=use_cache)
    if isinstance(body, dict):
        return body.get("data", [])
    return body
