from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


def _txt(el) -> Optional[str]:
    """Safe text extractor with stripping."""
    if el is None:
        return None
    s = el.get_text(" ", strip=True)
    return s or None


def _first(soup: BeautifulSoup, selectors: List[str]):
    """Return the first element matching any selector."""
    for sel in selectors:
        el = soup.select_one(sel)
        if el is not None:
            return el
    return None


def playlist_scraper(url: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Scrape a Spinitron-like playlist page (e.g., playlists.wprb.com) into a JSON-friendly dict.

    Returns:
        {
          "meta": {...},
          "tracks": [ {...}, ... ]
        }
    """
    headers = {
        # Polite UA helps avoid basic blocks; customize contact if you want.
        "User-Agent": "playlist-scraper/1.0 (contact: you@example.com)"
    }

    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # --- META ---
    fetched_at = datetime.now(timezone.utc).isoformat()
    canonical = None
    canon_el = soup.select_one('link[rel="canonical"]')
    if canon_el and canon_el.get("href"):
        canonical = canon_el["href"]

    title_text = _txt(soup.select_one("title"))
    h1_text = _txt(soup.select_one("h1"))

    # Try a few common places for station/network labeling
    station_text = _txt(_first(soup, [
        ".station-name",
        ".navbar-brand",
        "header .brand",
        "a[rel='home']",
    ]))

    meta: Dict[str, Any] = {
        "source_url": url,
        "canonical_url": canonical,
        "domain": urlparse(url).netloc,
        "fetched_at_utc": fetched_at,
        "page_title": title_text,
        "playlist_title": h1_text or title_text,
        "station": station_text,
    }

    # --- TRACKS / SPINS ---
    # Spinitron-ish pages often use td.spin-time and spans like .artist/.song/.release
    # but different themes exist. We'll search for plausible "row containers" first.
    row_selectors = [
        "tr.spin",              # common
        "tr.spin-item",         # common variant
        "tr.spinRow",           # variant
        "div.spin",             # sometimes div-based
        "div.spin-item",
        "li.spin",
    ]

    spin_rows = []
    for rs in row_selectors:
        found = soup.select(rs)
        if found:
            spin_rows = found
            break

    tracks: List[Dict[str, Any]] = []

    def extract_from_row(row) -> Optional[Dict[str, Any]]:
        # Time
        time_el = _first(row, [".spin-time", "td.spin-time", ".time", "td.time"])
        # Core fields
        artist_el = _first(row, ["span.artist", ".artist", "td.artist"])
        song_el = _first(row, ["span.song", ".song", "td.song", ".track", "td.track"])
        release_el = _first(row, ["span.release", ".release", "td.release", ".album", "td.album"])
        label_el = _first(row, ["span.label", ".label", "td.label"])

        artist = _txt(artist_el)
        song = _txt(song_el)

        # Filter out non-tracks
        if not artist and not song:
            return None

        out = {
            "time": _txt(time_el),
            "artist": artist,
            "song": song,
            "release": _txt(release_el),
            "label": _txt(label_el),
        }

        # Optional: try to grab links (artist/song pages) if present
        artist_link = artist_el.find("a") if artist_el else None
        song_link = song_el.find("a") if song_el else None
        out["artist_url"] = artist_link.get("href") if artist_link and artist_link.get("href") else None
        out["song_url"] = song_link.get("href") if song_link and song_link.get("href") else None

        # Normalize empty strings to None
        for k, v in list(out.items()):
            if isinstance(v, str) and not v.strip():
                out[k] = None

        return out

    if spin_rows:
        for row in spin_rows:
            item = extract_from_row(row)
            if item:
                tracks.append(item)
    else:
        # Fallback: field-list approach if no row container matched
        times = [t.get_text(strip=True) for t in soup.select("td.spin-time, .spin-time")]
        artists = [a.get_text(strip=True) for a in soup.select("span.artist, .artist")]
        songs = [s.get_text(strip=True) for s in soup.select("span.song, .song")]
        releases = [r.get_text(strip=True) for r in soup.select("span.release, .release")]

        # Only zip what we have; this is less robust but better than nothing.
        n = min(len(artists), len(songs), len(times) if times else 10**9, len(releases) if releases else 10**9)
        for i in range(n):
            tracks.append({
                "time": times[i] if times else None,
                "artist": artists[i],
                "song": songs[i],
                "release": releases[i] if releases else None,
                "label": None,
                "artist_url": None,
                "song_url": None,
            })

    # Add a couple useful derived meta fields
    meta["track_count"] = len(tracks)

    return {
        "meta": meta,
        "tracks": tracks,
    }


if __name__ == "__main__":
    test_url = "https://playlists.wprb.com/WPRB/pl/21686552/Lady-Love"
    data = playlist_scraper(test_url)
    print(json.dumps(data, indent=2, ensure_ascii=False))
