from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests


# ----------------------------
# Config (tweak as needed)
# ----------------------------

# Odesli/Songlink API base. (Common in-the-wild base; if it changes, update here.)
ODESLI_BASE = "https://api.song.link/v1-alpha.1"

# Basic, polite rate limiting (seconds between API calls)
SLEEP_BETWEEN_CALLS = 0.25

# Optional disk cache to avoid re-querying the same tracks repeatedly
CACHE_PATH = Path("link_cache.json")


# ----------------------------
# Helpers: normalization + scoring
# ----------------------------

def _norm(s: str) -> str:
    """Normalize for matching and scoring."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).lower()

    # Remove featuring parts that often differ across services
    s = re.sub(r"\s*\(feat\.?.*?\)", "", s)
    s = re.sub(r"\s*\[feat\.?.*?\]", "", s)
    s = re.sub(r"\s*feat\.?\s+.*$", "", s)

    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _token_overlap_score(want: str, got: str) -> float:
    """Cheap similarity score: token overlap."""
    w = set(_norm(want).split())
    g = set(_norm(got).split())
    if not w or not g:
        return 0.0
    return len(w & g) / max(len(w), 1)


def _is_close_enough(track: "TrackMeta", candidate: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Decide whether a candidate is a good match and produce a confidence score.
    Candidate dict comes from Deezer or iTunes results.
    """
    cand_artist = candidate.get("artist") or ""
    cand_title = candidate.get("title") or ""
    cand_album = candidate.get("album") or ""

    artist_score = _token_overlap_score(track.artist, cand_artist)
    title_score = _token_overlap_score(track.title, cand_title)

    # Album is optional because your playlist "release" field may vary (Singles, deluxe, etc.)
    album_score = 0.0
    if track.album and cand_album:
        album_score = _token_overlap_score(track.album, cand_album)

    # Weighted confidence: title matters most, then artist, then album
    confidence = (0.55 * title_score) + (0.35 * artist_score) + (0.10 * album_score)

    # A reasonable threshold for "good enough" without being too strict
    good = (title_score >= 0.6 and artist_score >= 0.5) or confidence >= 0.7
    return good, confidence


# ----------------------------
# Data model
# ----------------------------

@dataclass(frozen=True)
class TrackMeta:
    artist: str
    title: str
    album: Optional[str] = None


# ----------------------------
# Cache (optional but useful)
# ----------------------------

def load_cache(path: Path = CACHE_PATH) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: Dict[str, Any], path: Path = CACHE_PATH) -> None:
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def cache_key(track: TrackMeta) -> str:
    return f"{_norm(track.artist)}::{_norm(track.title)}::{_norm(track.album or '')}"


# ----------------------------
# Seed lookup: Deezer
# ----------------------------

def deezer_search_seed(track: TrackMeta, session: requests.Session) -> Optional[Dict[str, Any]]:
    """
    Return a dict with: seed_url, provider, confidence, raw
    or None if no good match.
    """
    # Deezer search endpoint
    # Docs are commonly referenced as: https://api.deezer.com/search/track?q=...
    q = f'{track.artist} {track.title}'
    url = "https://api.deezer.com/search/track?" + urlencode({"q": q, "limit": 10})

    time.sleep(SLEEP_BETWEEN_CALLS)
    r = session.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    best = None
    best_conf = 0.0

    for item in data.get("data", []):
        candidate = {
            "artist": (item.get("artist") or {}).get("name", ""),
            "title": item.get("title", ""),
            "album": (item.get("album") or {}).get("title", ""),
            "seed_url": item.get("link"),  # Deezer share link
        }
        good, conf = _is_close_enough(track, candidate)
        if good and conf > best_conf and candidate["seed_url"]:
            best = candidate
            best_conf = conf

    if not best:
        return None

    return {
        "provider": "deezer",
        "seed_url": best["seed_url"],
        "confidence": round(best_conf, 3),
        "matched": {
            "artist": best["artist"],
            "title": best["title"],
            "album": best["album"],
        },
        "raw": best,  # minimal raw
    }


# ----------------------------
# Seed lookup: iTunes Search API
# ----------------------------

def itunes_search_seed(track: TrackMeta, session: requests.Session) -> Optional[Dict[str, Any]]:
    """
    Return a dict with: seed_url, provider, confidence, raw
    or None if no good match.
    """
    # iTunes Search API endpoint:
    # https://itunes.apple.com/search?term=...&entity=song&limit=...
    term = f"{track.artist} {track.title}"
    params = {
        "term": term,
        "entity": "song",
        "limit": 10,
    }
    url = "https://itunes.apple.com/search?" + urlencode(params)

    time.sleep(SLEEP_BETWEEN_CALLS)
    r = session.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    best = None
    best_conf = 0.0

    for item in data.get("results", []):
        candidate = {
            "artist": item.get("artistName", ""),
            "title": item.get("trackName", ""),
            "album": item.get("collectionName", ""),
            # This is an Apple Music / iTunes preview/share-ish URL.
            # Aggregators often accept it as a seed.
            "seed_url": item.get("trackViewUrl"),
        }
        good, conf = _is_close_enough(track, candidate)
        if good and conf > best_conf and candidate["seed_url"]:
            best = candidate
            best_conf = conf

    if not best:
        return None

    return {
        "provider": "itunes",
        "seed_url": best["seed_url"],
        "confidence": round(best_conf, 3),
        "matched": {
            "artist": best["artist"],
            "title": best["title"],
            "album": best["album"],
        },
        "raw": best,
    }


# ----------------------------
# Album seed lookup: Deezer
# ----------------------------

def deezer_search_album_seed(track: TrackMeta, session: requests.Session) -> Optional[Dict[str, Any]]:
    """
    Return a dict with: seed_url, provider, confidence, raw
    or None if no good match.
    """
    if not track.album:
        return None
    
    # Deezer search endpoint for albums
    q = f'{track.artist} {track.album}'
    url = "https://api.deezer.com/search/album?" + urlencode({"q": q, "limit": 10})

    time.sleep(SLEEP_BETWEEN_CALLS)
    r = session.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    best = None
    best_conf = 0.0

    for item in data.get("data", []):
        candidate_artist = (item.get("artist") or {}).get("name", "")
        candidate_album = item.get("title", "")
        
        artist_score = _token_overlap_score(track.artist, candidate_artist)
        album_score = _token_overlap_score(track.album, candidate_album)
        
        # For albums, we care more about album name match, but artist should be reasonable
        confidence = (0.7 * album_score) + (0.3 * artist_score)
        good = (album_score >= 0.6 and artist_score >= 0.4) or confidence >= 0.7
        
        if good and confidence > best_conf:
            album_url = item.get("link")  # Deezer album link
            if album_url:
                best = {
                    "artist": candidate_artist,
                    "album": candidate_album,
                    "seed_url": album_url,
                }
                best_conf = confidence

    if not best:
        return None

    return {
        "provider": "deezer",
        "seed_url": best["seed_url"],
        "confidence": round(best_conf, 3),
        "matched": {
            "artist": best["artist"],
            "album": best["album"],
        },
        "raw": best,
    }


# ----------------------------
# Album seed lookup: iTunes Search API
# ----------------------------

def itunes_search_album_seed(track: TrackMeta, session: requests.Session) -> Optional[Dict[str, Any]]:
    """
    Return a dict with: seed_url, provider, confidence, raw
    or None if no good match.
    """
    if not track.album:
        return None
    
    # iTunes Search API endpoint for albums
    term = f"{track.artist} {track.album}"
    params = {
        "term": term,
        "entity": "album",
        "limit": 10,
    }
    url = "https://itunes.apple.com/search?" + urlencode(params)

    time.sleep(SLEEP_BETWEEN_CALLS)
    r = session.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    best = None
    best_conf = 0.0

    for item in data.get("results", []):
        candidate_artist = item.get("artistName", "")
        candidate_album = item.get("collectionName", "")
        
        artist_score = _token_overlap_score(track.artist, candidate_artist)
        album_score = _token_overlap_score(track.album, candidate_album)
        
        # For albums, we care more about album name match, but artist should be reasonable
        confidence = (0.7 * album_score) + (0.3 * artist_score)
        good = (album_score >= 0.6 and artist_score >= 0.4) or confidence >= 0.7
        
        if good and confidence > best_conf:
            album_url = item.get("collectionViewUrl")  # iTunes album URL
            if album_url:
                best = {
                    "artist": candidate_artist,
                    "album": candidate_album,
                    "seed_url": album_url,
                }
                best_conf = confidence

    if not best:
        return None

    return {
        "provider": "itunes",
        "seed_url": best["seed_url"],
        "confidence": round(best_conf, 3),
        "matched": {
            "artist": best["artist"],
            "album": best["album"],
        },
        "raw": best,
    }


# ----------------------------
# Link expansion: Odesli/Songlink
# ----------------------------

def odesli_expand(seed_url: str, session: requests.Session) -> Dict[str, Any]:
    """
    Call Odesli and return platform links.

    Returns:
      {
        "page_url": "...",              # a universal song.link page (if available)
        "links_by_platform": {...},     # platform -> url
        "raw": {...}                    # raw response
      }
    """
    # Common Odesli endpoint:
    # GET {ODESLI_BASE}/links?url=<seed_url>
    url = f"{ODESLI_BASE}/links?" + urlencode({"url": seed_url})

    time.sleep(SLEEP_BETWEEN_CALLS)
    r = session.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()

    # Normalize the response into a simple map
    links: Dict[str, Optional[str]] = {}

    links_by_platform = data.get("linksByPlatform") or {}
    for platform, payload in links_by_platform.items():
        if isinstance(payload, dict):
            links[platform] = payload.get("url")
        else:
            links[platform] = None

    # Some responses include a canonical "page" / "songlink"
    page_url = None
    # Not guaranteed; try a few common places
    if isinstance(data.get("pageUrl"), str):
        page_url = data["pageUrl"]
    elif isinstance(data.get("url"), str):
        page_url = data["url"]

    return {
        "page_url": page_url,
        "links_by_platform": links,
        "raw": data,
    }


# ----------------------------
# Main function: metadata -> platform share URLs
# ----------------------------

def find_share_urls_from_metadata(
    track: TrackMeta,
    session: Optional[requests.Session] = None,
    use_cache: bool = True,
    cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Starting from metadata only:
      - find a seed URL (Deezer first, then iTunes)
      - expand via Odesli
      - return links to target services when available

    Output is JSON-friendly and designed to be attached to your playlist track dict.
    """
    own_session = session is None
    if session is None:
        session = requests.Session()

    try:
        if cache is None and use_cache:
            cache = load_cache()

        key = cache_key(track)
        if use_cache and cache is not None and key in cache:
            return cache[key]

        # 1) Seed lookup
        seed = deezer_search_seed(track, session)
        if seed is None:
            seed = itunes_search_seed(track, session)

        if seed is None:
            result = {
                "ok": False,
                "reason": "no_seed_match",
                "track": {"artist": track.artist, "title": track.title, "album": track.album},
                "seed": None,
                "aggregated": None,
                "targets": {},
            }
            if use_cache and cache is not None:
                cache[key] = result
                save_cache(cache)
            return result

        # 2) Expand track links
        aggregated = odesli_expand(seed["seed_url"], session)

        # 3) Pull out your target platforms (keys vary; keep both raw and filtered)
        links = aggregated["links_by_platform"]

        targets = {
            "amazon_music": links.get("amazonMusic") or links.get("amazon"),
            "soundcloud": links.get("soundcloud"),
            "qobuz": links.get("qobuz"),
            "deezer": links.get("deezer"),
            "tidal": links.get("tidal"),
        }

        # 4) Search for album URLs if album is provided
        album_seed = None
        album_aggregated = None
        album_targets = {}
        album_links_by_platform = {}
        
        if track.album:
            album_seed = deezer_search_album_seed(track, session)
            if album_seed is None:
                album_seed = itunes_search_album_seed(track, session)
            
            if album_seed:
                album_aggregated = odesli_expand(album_seed["seed_url"], session)
                album_links = album_aggregated["links_by_platform"]
                
                album_targets = {
                    "amazon_music": album_links.get("amazonMusic") or album_links.get("amazon"),
                    "soundcloud": album_links.get("soundcloud"),
                    "qobuz": album_links.get("qobuz"),
                    "deezer": album_links.get("deezer"),
                    "tidal": album_links.get("tidal"),
                }
                album_links_by_platform = album_links

        result = {
            "ok": True,
            "track": {"artist": track.artist, "title": track.title, "album": track.album},
            "seed": seed,
            "aggregated": {
                "page_url": aggregated.get("page_url"),
                "targets": targets,
            },
            # Keep full links map if you want everything, not just the targets
            "links_by_platform": links,
            # Album links
            "album_seed": album_seed,
            "album_aggregated": {
                "page_url": album_aggregated.get("page_url") if album_aggregated else None,
                "targets": album_targets,
            } if album_aggregated else None,
            "album_links_by_platform": album_links_by_platform if album_links_by_platform else {},
        }

        if use_cache and cache is not None:
            cache[key] = result
            save_cache(cache)

        return result

    finally:
        if own_session:
            session.close()


# ----------------------------
# Optional: enrich your playlist JSON in-place
# ----------------------------

def enrich_playlist_with_links(playlist_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes your playlist_scraper output dict and adds share links for each track:
      track["share_links"] = {...}
    """
    s = requests.Session()
    cache = load_cache()

    try:
        for t in playlist_data.get("tracks", []):
            meta = TrackMeta(
                artist=t.get("artist") or "",
                title=t.get("song") or "",
                album=t.get("release"),
            )
            res = find_share_urls_from_metadata(meta, session=s, use_cache=True, cache=cache)

            # Attach a compact version (you can attach the whole result if you prefer)
            if res.get("ok"):
                t["share_links"] = res["aggregated"]["targets"]
                t["songlink_page"] = res["aggregated"].get("page_url")
                t["link_seed"] = res.get("seed")
            else:
                t["share_links"] = {}
                t["songlink_page"] = None
                t["link_seed"] = res.get("seed")

        # Optionally update meta with an indicator
        playlist_data.setdefault("meta", {})
        playlist_data["meta"]["links_enriched"] = True
        playlist_data["meta"]["links_cache_file"] = str(CACHE_PATH)

        # Persist cache at end (if we loaded it)
        save_cache(cache)

        return playlist_data
    finally:
        s.close()


# ----------------------------
# Example usage
# ----------------------------

if __name__ == "__main__":
    # Example: load your scraped output JSON and enrich it
    # (Assumes you saved your scraper output to playlist.json)
    input_path = Path("playlist.json")
    if input_path.exists():
        playlist = json.loads(input_path.read_text(encoding="utf-8"))
        enriched = enrich_playlist_with_links(playlist)
        Path("playlist.enriched.json").write_text(
            json.dumps(enriched, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print("Wrote playlist.enriched.json")
    else:
        # Quick one-off test:
        test = TrackMeta(artist="Frankie Cosmos", title="Vanity", album="Different Talking")
        print(json.dumps(find_share_urls_from_metadata(test), indent=2, ensure_ascii=False))
