from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".aiff", ".aif", ".ogg", ".opus", ".alac"}


def _norm(s: str) -> str:
    """Normalize for matching (casefold, strip punctuation, normalize quotes, remove feat.)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).lower()
    s = re.sub(r"\s*\(feat\.?.*?\)", "", s)
    s = re.sub(r"\s*\[feat\.?.*?\]", "", s)
    s = re.sub(r"\s*feat\.?\s+.*$", "", s)
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _safe_filename(s: str, max_len: int = 180) -> str:
    """Make a filesystem-friendly filename chunk."""
    s = s or "unknown"
    s = unicodedata.normalize("NFKD", s)
    s = s.replace("/", "-")
    s = re.sub(r"[\s]+", " ", s).strip()
    s = re.sub(r'[<>:"\\|?*\x00-\x1f]', "", s)  # unsafe chars
    return s[:max_len].strip() or "unknown"


def _iter_audio_files(library_root: Path):
    for p in library_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            yield p


def _extract_track_name_from_filename(filename_stem: str, artist: str) -> str:
    """
    Try to extract just the track name from a filename that might include artist name or track numbers.
    
    Handles formats like:
    - "Artist - Track Name"
    - "Track Name"
    - "02. Track Name"
    - "1. Track Name"
    - "Artist-Track Name"
    - etc.
    """
    norm_stem = _norm(filename_stem)
    norm_artist = _norm(artist)
    
    # Remove track numbers at the start (e.g., "02. BIG" -> "BIG")
    norm_stem = re.sub(r'^\d+\.?\s+', '', norm_stem)
    
    # If filename starts with artist name, try to remove it
    if norm_stem.startswith(norm_artist):
        # Try "Artist - Track" or "Artist-Track" pattern
        remaining = norm_stem[len(norm_artist):].strip()
        # Remove leading dash/hyphen/separator
        remaining = re.sub(r'^[-\s]+', '', remaining)
        if remaining:
            return remaining
    
    # Also try splitting on common separators
    parts = re.split(r'\s*-\s*|\s*–\s*|\s*—\s*', norm_stem)
    if len(parts) > 1:
        # If first part matches artist, return second part
        if _norm(parts[0]) == norm_artist and len(parts) > 1:
            return ' '.join(parts[1:])
        # Otherwise, return the last part (often the track name)
        return parts[-1]
    
    return norm_stem


def _normalize_album_name(album: str) -> str:
    """
    Normalize album name by removing common suffixes/patterns that vary.
    
    Removes:
    - "- Single", "- EP", "- Album"
    - "(2023)", "(2024)", etc.
    - Leading/trailing whitespace variations
    
    Note: This should be called on the original album name, not the normalized one,
    because we need to preserve punctuation for pattern matching.
    """
    if not album:
        return ""
    
    # Remove common suffixes BEFORE normalization (to preserve punctuation)
    # Remove "- Single", "- EP", etc.
    album = re.sub(r'\s*-\s*(single|ep|album|lp)\s*$', '', album, flags=re.IGNORECASE)
    
    # Remove year patterns like "(2023)" or "[2023]"
    album = re.sub(r'\s*[\[\(]\d{4}[\]\)]\s*$', '', album)
    
    # Now normalize
    return _norm(album).strip()


def _build_index(library_root: Path) -> Dict[Tuple[str, str, str], List[Path]]:
    """
    Index assumes: Library/Artist/Album/Track.ext
    key = (norm_artist, norm_album, norm_track_stem)
    
    Also indexes alternative keys for flexible matching:
    - (norm_artist, norm_album, extracted_track_name) where track name is extracted from filename
    - (norm_artist, normalized_album, ...) with normalized album names
    """
    index: Dict[Tuple[str, str, str], List[Path]] = {}
    for f in _iter_audio_files(library_root):
        album_dir = f.parent
        artist_dir = album_dir.parent
        artist = artist_dir.name
        album = album_dir.name
        track_stem = f.stem
        
        norm_artist = _norm(artist)
        norm_album = _norm(album)
        norm_track = _norm(track_stem)
        norm_album_flexible = _normalize_album_name(album)
        
        # Primary key: exact match
        key = (norm_artist, norm_album, norm_track)
        index.setdefault(key, []).append(f)
        
        # Alternative key 1: extracted track name (handles "Artist - Song" and "02. Song" formats)
        extracted_track = _extract_track_name_from_filename(track_stem, artist)
        if extracted_track != norm_track:
            alt_key1 = (norm_artist, norm_album, extracted_track)
            index.setdefault(alt_key1, []).append(f)
            
            # Also with normalized album name
            if norm_album_flexible != norm_album:
                alt_key1b = (norm_artist, norm_album_flexible, extracted_track)
                index.setdefault(alt_key1b, []).append(f)
        
        # Alternative key 2: normalized album name (handles "Album - EP" vs "Album")
        if norm_album_flexible != norm_album:
            alt_key2 = (norm_artist, norm_album_flexible, norm_track)
            index.setdefault(alt_key2, []).append(f)
            
            # Combined: normalized album + extracted track
            if extracted_track != norm_track:
                alt_key2b = (norm_artist, norm_album_flexible, extracted_track)
                index.setdefault(alt_key2b, []).append(f)
    
    return index


def _pick_best_candidate(song: str, candidates: List[Path]) -> Optional[Path]:
    """
    Pick the best candidate among same-artist+album candidates.
    Cheap scoring: token overlap between desired title and candidate filename stem.
    """
    want = set(_norm(song).split())
    if not want:
        return candidates[0] if candidates else None

    best_score = -1
    best_path = None
    for p in candidates:
        have = set(_norm(p.stem).split())
        score = len(want & have)
        if score > best_score:
            best_score = score
            best_path = p

    return best_path


def export_playlist_copies(
    data: Dict[str, Any],
    base_folder: str | Path,
    target_dir: str | Path,
    library_subpath: str = "Music/Library",
    make_subfolder: bool = True,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Find each playlist track in your library and copy it into target_dir
    in playlist order, with numeric prefixes (01, 02, ...).

    Parameters
    ----------
    data : dict
        Output from playlist_scraper (meta + tracks).
    base_folder : str|Path
        Base folder that contains the library (e.g., "/Users/username" or "/Volumes/Music Library").
    target_dir : str|Path
        Where to copy the playlist files.
    library_subpath : str
        Library location relative to base_folder ("Music/Library" by default).
        If base_folder already IS the Library root, pass library_subpath="".
    make_subfolder : bool
        If True, create a subfolder named from playlist metadata inside target_dir.
    overwrite : bool
        If True, overwrite existing files in the target.

    Returns
    -------
    JSON-friendly report with paths + match status, and writes manifest.json.
    """
    base = Path(base_folder).expanduser()
    library_root = (base / library_subpath).resolve() if library_subpath else base.resolve()
    if not library_root.exists():
        raise FileNotFoundError(f"Library root not found: {library_root}")

    target_root = Path(target_dir).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    meta = data.get("meta", {}) or {}
    tracks = data.get("tracks", []) or []

    # Decide destination folder name
    dest_folder = target_root
    if make_subfolder:
        # Use playlist page title or canonical URL slug as the folder name
        title = meta.get("page_title") or meta.get("canonical_url") or "playlist"
        # Try to include date if present in fetched_at_utc
        fetched = meta.get("fetched_at_utc", "")
        date_prefix = fetched[:10] if isinstance(fetched, str) and len(fetched) >= 10 else ""
        folder_name = f"{date_prefix} - {title}" if date_prefix else str(title)
        folder_name = _safe_filename(folder_name)
        dest_folder = target_root / folder_name
        dest_folder.mkdir(parents=True, exist_ok=True)

    # Build fast lookup index once
    index = _build_index(library_root)

    # Also build grouping by (artist, album) for “best candidate” fallback
    artist_album_to_paths: Dict[Tuple[str, str], List[Path]] = {}
    for (a, al, _t), paths in index.items():
        artist_album_to_paths.setdefault((a, al), []).extend(paths)

    report_results: List[Dict[str, Any]] = []
    copied = 0
    missing = 0

    # Copy in playlist order
    pad = max(2, len(str(len(tracks))))

    for i, t in enumerate(tracks, start=1):
        artist = t.get("artist") or ""
        album = t.get("release") or ""
        song = t.get("song") or ""

        # Try multiple matching strategies (same as match_playlist_to_library)
        matches = []
        norm_artist = _norm(artist)
        norm_album = _norm(album)
        norm_album_flexible = _normalize_album_name(album)
        norm_title = _norm(song)
        
        # Strategy 1: Exact match (artist, album, track)
        key = (norm_artist, norm_album, norm_title)
        matches.extend(index.get(key, []))
        
        # Strategy 2: With normalized album name
        if not matches and norm_album_flexible != norm_album:
            key2 = (norm_artist, norm_album_flexible, norm_title)
            matches.extend(index.get(key2, []))
        
        # Strategy 3: Try matching with extracted track name from files
        if not matches:
            for alt_album in [norm_album, norm_album_flexible]:
                if alt_album:
                    key3 = (norm_artist, alt_album, norm_title)
                    matches.extend(index.get(key3, []))
        
        # Strategy 4: Token-based fuzzy matching within same artist/album
        if not matches:
            title_tokens = set(norm_title.split())
            if title_tokens:
                for (a, al, track_name), paths in index.items():
                    if a == norm_artist:
                        album_matches = (al == norm_album or 
                                       (norm_album_flexible and al == norm_album_flexible))
                        if album_matches:
                            track_tokens = set(track_name.split())
                            if title_tokens.issubset(track_tokens):
                                matches.extend(paths)
        
        # Strategy 5: Fallback - match by artist + track only (ignore album)
        if not matches:
            for (a, al, track_name), paths in index.items():
                if a == norm_artist and track_name == norm_title:
                    matches.extend(paths)
            
            if not matches:
                title_tokens = set(norm_title.split())
                for (a, al, track_name), paths in index.items():
                    if a == norm_artist:
                        track_tokens = set(track_name.split())
                        if title_tokens and title_tokens.issubset(track_tokens) and len(title_tokens) >= 2:
                            matches.extend(paths)
        
        # Strategy 6: Check Various Artists / Compilation albums
        # Handles cases where tracks are in compilation albums under "Various Artists" or similar
        if not matches:
            # Common variations of "Various Artists" folder names
            various_artists_names = [
                "various artists",
                "various",
                "va",
                "compilation",
                "compilations",
                "soundtrack",
                "soundtracks",
                "ost",
            ]
            
            # Try matching track in Various Artists folders with same album
            for va_name in various_artists_names:
                norm_va = _norm(va_name)
                # Try with album match first
                for alt_album in [norm_album, norm_album_flexible]:
                    if alt_album:
                        key_va = (norm_va, alt_album, norm_title)
                        matches.extend(index.get(key_va, []))
                
                # If no album match, try just track name match in Various Artists
                if not matches:
                    for (a, al, track_name), paths in index.items():
                        if a == norm_va and track_name == norm_title:
                            matches.extend(paths)
                    
                    # Also try token-based matching
                    if not matches:
                        title_tokens = set(norm_title.split())
                        for (a, al, track_name), paths in index.items():
                            if a == norm_va:
                                track_tokens = set(track_name.split())
                                if title_tokens and title_tokens.issubset(track_tokens) and len(title_tokens) >= 2:
                                    matches.extend(paths)
                
                # If we found matches, stop checking other VA variations
                if matches:
                    break
        
        # Remove duplicates
        seen = set()
        unique_matches = []
        for p in matches:
            if p not in seen:
                seen.add(p)
                unique_matches.append(p)
        matches = unique_matches

        chosen: Optional[Path] = None
        match_type = None

        if matches:
            chosen = matches[0]
            match_type = "exact"
        else:
            # Final fallback: look at all tracks from same artist+album and pick best filename
            candidates = artist_album_to_paths.get((norm_artist, norm_album), [])
            if not candidates and norm_album_flexible != norm_album:
                candidates = artist_album_to_paths.get((norm_artist, norm_album_flexible), [])
            chosen = _pick_best_candidate(song, candidates)
            match_type = "candidate" if chosen else None

        item: Dict[str, Any] = {
            "order": i,
            "time": t.get("time"),
            "artist": artist,
            "album": album,
            "song": song,
            "match_type": match_type,
            "source_path": str(chosen) if chosen else None,
            "copied_path": None,
        }

        if not chosen:
            missing += 1
            report_results.append(item)
            continue

        # Build destination filename with numeric order prefix
        prefix = str(i).zfill(pad)
        ext = chosen.suffix.lower()
        dest_name = f"{prefix} - {_safe_filename(artist)} - {_safe_filename(song)}{ext}"
        dest_path = dest_folder / dest_name

        if dest_path.exists() and not overwrite:
            # Don’t overwrite; still record as “already there”
            item["copied_path"] = str(dest_path)
            item["note"] = "exists (not overwritten)"
            report_results.append(item)
            continue

        shutil.copy2(chosen, dest_path)
        copied += 1
        item["copied_path"] = str(dest_path)
        report_results.append(item)

    manifest = {
        "meta": meta,
        "library_root": str(library_root),
        "destination_folder": str(dest_folder),
        "summary": {
            "total_tracks": len(tracks),
            "copied": copied,
            "missing": missing,
        },
        "results": report_results,
    }

    # Write manifest alongside the copied files
    with open(dest_folder / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return manifest
