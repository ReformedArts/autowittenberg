"""Small JSON-file-backed caches, so each listing's copy and each photo's classification
is only ever generated once, keeping Claude API costs minimal and results stable.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
COPY_CACHE_PATH = DATA_DIR / "listing_copy.json"
PHOTO_CACHE_PATH = DATA_DIR / "photo_classifications.json"


def _load(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_copy_cache():
    return _load(COPY_CACHE_PATH)


def save_copy_cache(cache):
    _save(COPY_CACHE_PATH, cache)


SNAPSHOT_PATH = DATA_DIR / "listings.json"
KNOWN_IDS_PATH = DATA_DIR / "known_listing_ids.json"
ROTATION_PATH = DATA_DIR / "rotation_state.json"
FIRST_SEEN_PATH = DATA_DIR / "listing_first_seen.json"


def load_snapshot():
    return _load(SNAPSHOT_PATH) or None


def save_snapshot(snapshot):
    _save(SNAPSHOT_PATH, snapshot)


def load_known_listing_ids():
    path = KNOWN_IDS_PATH
    return json.loads(path.read_text()) if path.exists() else []


def save_known_listing_ids(ids):
    _save(KNOWN_IDS_PATH, ids)


def load_first_seen():
    """{listing_id: 'YYYY-MM-DD'} -- the day AutoWittenberg first noticed each listing."""
    return _load(FIRST_SEEN_PATH)


def save_first_seen(data):
    _save(FIRST_SEEN_PATH, data)


def load_rotation():
    """{"posts": [{listing_id, image_id, palette, crop_style, headline, board, pin_id, posted_at}],
    "last_sync_date": "YYYY-MM-DD"}"""
    data = _load(ROTATION_PATH)
    data.setdefault("posts", [])
    return data


def save_rotation(data):
    _save(ROTATION_PATH, data)


def load_photo_cache():
    return _load(PHOTO_CACHE_PATH)


def save_photo_cache(cache):
    _save(PHOTO_CACHE_PATH, cache)
