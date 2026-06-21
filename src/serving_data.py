"""
Two-track delivery for the serving artifacts (model + parquet files).

The repo holds a committed *snapshot* so a fresh clone runs the app offline. The
daily refresh, instead of committing fresh artifacts (binary churn that bloats
git history), uploads them to a GitHub Release. This module prefers that release
- downloaded into a local cache and refreshed on a TTL - and transparently falls
back to the committed snapshot when the release is unreachable.

Stdlib only (urllib), so both the Streamlit app and the CLI predictor can use it
without extra dependencies.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("serving_data")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "_serving_cache"

# The release the refresh keeps current. A fixed tag whose assets are clobbered
# each run, so this base URL is stable.
RELEASE_BASE = (
    "https://github.com/ezra-gg/knicks-win-probability/releases/download/serving-latest"
)
# Re-fetch a cached artifact at most this often. The live app picks up a refresh
# within this window; the CLI just reuses a recent download.
TTL_SECONDS = 6 * 3600


def _is_fresh(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < TTL_SECONDS


def _download(name: str, dest: Path) -> None:
    """Fetch one release asset to dest atomically (via a temp file)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    urllib.request.urlretrieve(f"{RELEASE_BASE}/{name}", tmp)  # noqa: S310 - fixed https URL
    tmp.replace(dest)


def serving_file(name: str, fallback: Path) -> Path:
    """Local path to a serving artifact, preferring a fresh release copy.

    Returns the cached release download if recent; otherwise tries to fetch it,
    and on any failure (offline, release missing) returns the committed snapshot.
    """
    cached = CACHE_DIR / name
    if _is_fresh(cached):
        return cached
    try:
        _download(name, cached)
        return cached
    except (urllib.error.URLError, OSError) as exc:
        log.warning("serving: release fetch failed for %s (%s); using snapshot.",
                    name, type(exc).__name__)
        return cached if cached.exists() else fallback


def serving_model(model_fallback: Path, sidecar_fallback: Path) -> Path:
    """Path to the model JSON, with its feature sidecar co-located.

    load_model derives the sidecar as the model's sibling, so the two must live
    in the same directory. Fetch both into the cache together, or fall back to
    the committed pair (whose sidecar already sits beside the model in models/).
    """
    cached_model = CACHE_DIR / model_fallback.name
    if _is_fresh(cached_model):
        return cached_model
    try:
        _download(model_fallback.name, cached_model)
        _download(sidecar_fallback.name, CACHE_DIR / sidecar_fallback.name)
        return cached_model
    except (urllib.error.URLError, OSError) as exc:
        log.warning("serving: release model fetch failed (%s); using snapshot.",
                    type(exc).__name__)
        return cached_model if cached_model.exists() else model_fallback
