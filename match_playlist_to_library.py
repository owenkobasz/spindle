from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple


AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".aiff", ".aif", ".ogg", ".opus", ".alac"}


def _norm(s: str) -> str:
    """
    Normalize strings to improve match rate across:
    - case differences
    - curly quotes vs straight quotes
    - punctuation
    - extra whitespace
    - common 'feat.' patterns
    """
    if s is None:
        return ""

    # Normalize unicode (e.g., “I’ll” → "I'll" in many cases)
    s = unicodedata.normalize("NFKD", s)

    s = s.lower()

    # Remove common featuring patterns from titles/artists
    s = re.sub(r"\s*\(feat\.?.*?\)", "", s)
    s = re.sub(r"\s*\[feat\.?.*?\]", "", s)
    s = re.sub(r"\s*feat\.?\s+.*$", "", s)

    # Replace & with and (common difference in file naming)
    s = s.replace("&", "and")

    # Drop punctuation (keep letters/numbers/spaces)
    s = re.sub(r"[^a-z0-9\s]", "", s)

    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()

    return s


def _iter_audio_files(library_root: Path):
    """Yield all audio files under library_root."""
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
    
    This is critical for matching files created by catalog_music which adds track numbers like "01. Track Name".
    """
    # First, normalize the stem to handle the matching normalization
    # But we need to preserve structure for extraction, so normalize after extraction
    norm_artist = _norm(artist)
    
    # Remove track numbers at the start FIRST (e.g., "01. Track Name" -> "Track Name")
    # Handle both "01. " and "1. " formats
    cleaned_stem = re.sub(r'^\d+\.?\s+', '', filename_stem)
    
    # Now normalize the cleaned stem
    norm_stem = _norm(cleaned_stem)
    
    # If filename starts with artist name, try to remove it
    if norm_stem.startswith(norm_artist):
        # Try "Artist - Track" or "Artist-Track" pattern
        remaining = norm_stem[len(norm_artist):].strip()
        # Remove leading dash/hyphen/separator
        remaining = re.sub(r'^[-\s]+', '', remaining)
        if remaining:
            return remaining
    
    # Also try splitting on common separators (on the original cleaned stem before normalization)
    parts = re.split(r'\s*-\s*|\s*–\s*|\s*—\s*', cleaned_stem)
    if len(parts) > 1:
        # Normalize first part and check if it matches artist
        if _norm(parts[0]) == norm_artist and len(parts) > 1:
            # Return normalized version of the track name part
            return _norm(' '.join(parts[1:]))
        # Otherwise, return the last part (often the track name)
        return _norm(parts[-1])
    
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
    Build an index: (norm_artist, norm_album, norm_track_stem) -> [paths...]

    Assumes folder structure:
        Library/Artist/Album/Track.ext
    
    Also indexes alternative keys for flexible matching:
    - (norm_artist, norm_album, extracted_track_name) where track name is extracted from filename
    - (norm_artist, normalized_album, ...) with normalized album names
    """
    index: Dict[Tuple[str, str, str], List[Path]] = {}

    for f in _iter_audio_files(library_root):
        # Expect .../Artist/Album/Track.ext
        try:
            album_dir = f.parent
            artist_dir = album_dir.parent
            artist = artist_dir.name
            album = album_dir.name
            track_stem = f.stem  # filename without extension
        except Exception:
            continue

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
        
        # Alternative key 3: track name without parenthetical content
        # Handles "Dancing (2020 Version)" vs "Dancing"
        track_no_parens = re.sub(r'\s*\([^)]*\)\s*', ' ', track_stem)
        track_no_parens = re.sub(r'\s*\[[^\]]*\]\s*', ' ', track_no_parens)
        track_no_parens = track_no_parens.strip()
        if track_no_parens and track_no_parens != track_stem:
            norm_track_no_parens = _norm(track_no_parens)
            if norm_track_no_parens != norm_track:
                # With original album
                alt_key3 = (norm_artist, norm_album, norm_track_no_parens)
                index.setdefault(alt_key3, []).append(f)
                # With normalized album
                if norm_album_flexible != norm_album:
                    alt_key3b = (norm_artist, norm_album_flexible, norm_track_no_parens)
                    index.setdefault(alt_key3b, []).append(f)
                # Also extract track name from the cleaned version
                extracted_no_parens = _extract_track_name_from_filename(track_no_parens, artist)
                if extracted_no_parens != norm_track_no_parens:
                    alt_key3c = (norm_artist, norm_album, extracted_no_parens)
                    index.setdefault(alt_key3c, []).append(f)
                    if norm_album_flexible != norm_album:
                        alt_key3d = (norm_artist, norm_album_flexible, extracted_no_parens)
                        index.setdefault(alt_key3d, []).append(f)

    return index


def match_playlist_to_library(
    data: Dict[str, Any],
    base_folder: str | Path,
    library_subpath: str = "Music/Library",
    include_candidates: bool = True,
    max_candidates: int = 5,
) -> Dict[str, Any]:
    """
    Match scraped playlist data against a local music library.

    Parameters
    ----------
    data : dict
        The output from playlist_scraper (meta + tracks).
    base_folder : str|Path
        Base folder you want to search from (e.g., "/Users/username" or "/Volumes/Music Library").
    library_subpath : str
        Where the library lives relative to base_folder.
        Default: "Music/Library"
        If your base_folder already *is* the Library folder, set library_subpath="".
    include_candidates : bool
        If True, include "near misses" (same artist+album, track name similar-ish).
    max_candidates : int
        Cap the number of candidate paths returned per missing track.

    Returns
    -------
    JSON-friendly dict including:
        - meta (pass-through)
        - summary (counts)
        - results: per-track match info
    """
    base = Path(base_folder).expanduser()
    library_root = (base / library_subpath).resolve() if library_subpath else base.resolve()

    if not library_root.exists():
        raise FileNotFoundError(f"Library root not found: {library_root}")

    # 1) Index your library ONCE (fast lookups afterwards)
    index = _build_index(library_root)

    results: List[Dict[str, Any]] = []
    found_count = 0

    # Optional: precompute a lightweight artist+album grouping for candidate search
    artist_album_to_paths: Dict[Tuple[str, str], List[Path]] = {}
    if include_candidates:
        for (a, al, _t), paths in index.items():
            artist_album_to_paths.setdefault((a, al), []).extend(paths)

    for track in data.get("tracks", []):
        artist = track.get("artist") or ""
        album = track.get("release") or ""
        title = track.get("song") or ""

        # Try multiple matching strategies
        matches = []
        norm_artist = _norm(artist)
        norm_album = _norm(album)
        norm_album_flexible = _normalize_album_name(album)
        norm_title = _norm(title)
        
        # Strategy 1: Exact match (artist, album, track)
        key = (norm_artist, norm_album, norm_title)
        matches.extend(index.get(key, []))
        
        # Strategy 2: With normalized album name
        if not matches and norm_album_flexible != norm_album:
            key2 = (norm_artist, norm_album_flexible, norm_title)
            matches.extend(index.get(key2, []))
        
        # Strategy 3: Try matching with extracted track name from files
        # (handles "Artist - Song.flac" and "02. Song.flac" formats)
        # The index already has alternative keys with extracted track names, so we need to
        # simulate what the extraction would do for the playlist title
        if not matches:
            # Try with normalized album variations
            for alt_album in [norm_album, norm_album_flexible]:
                if alt_album:
                    # Direct lookup (index should have this from extracted track names)
                    key3 = (norm_artist, alt_album, norm_title)
                    matches.extend(index.get(key3, []))
                    
                    # Also try if the title itself needs extraction (e.g., "Artist - Title" format)
                    # This handles cases where playlist has "Artist - Title" but file is "01. Title"
                    extracted_playlist_title = _extract_track_name_from_filename(title, artist)
                    if extracted_playlist_title != norm_title:
                        key3b = (norm_artist, alt_album, extracted_playlist_title)
                        matches.extend(index.get(key3b, []))
        
        # Strategy 4: Token-based fuzzy matching within same artist/album
        # (fallback for edge cases)
        if not matches:
            title_tokens = set(norm_title.split())
            if title_tokens:
                for (a, al, t), paths in index.items():
                    if a == norm_artist:
                        # Try both exact album and normalized album match
                        album_matches = (al == norm_album or 
                                       (norm_album_flexible and al == norm_album_flexible))
                        if album_matches:
                            # Check if track name tokens are contained in filename
                            track_tokens = set(t.split())
                            # If all title tokens are in track name, it's a match
                            if title_tokens.issubset(track_tokens):
                                matches.extend(paths)
                            # Also try reverse: if track tokens are subset of title (handles parenthetical content)
                            elif track_tokens.issubset(title_tokens) and len(track_tokens) >= 2:
                                matches.extend(paths)
                            # Or if there's significant overlap (at least 2/3 of shorter set)
                            elif title_tokens and track_tokens:
                                overlap = len(title_tokens & track_tokens)
                                min_len = min(len(title_tokens), len(track_tokens))
                                if min_len >= 2 and overlap >= (min_len * 2 // 3):
                                    matches.extend(paths)
        
        # Strategy 5: Try matching title without parenthetical content
        # Handles cases like "Dancing (2020 Version)" vs "Dancing"
        if not matches:
            # Remove parenthetical content from title (e.g., "(2020 Version)", "[Remix]", etc.)
            title_no_parens = re.sub(r'\s*\([^)]*\)\s*', ' ', title)
            title_no_parens = re.sub(r'\s*\[[^\]]*\]\s*', ' ', title_no_parens)
            title_no_parens = title_no_parens.strip()
            if title_no_parens and title_no_parens != title:
                norm_title_no_parens = _norm(title_no_parens)
                for alt_album in [norm_album, norm_album_flexible]:
                    if alt_album:
                        key5 = (norm_artist, alt_album, norm_title_no_parens)
                        matches.extend(index.get(key5, []))
        
        # Strategy 6: Fallback - match by artist + track only (ignore album)
        # This handles cases where album names are completely different
        # (e.g., playlist says "BIG - Single" but file is in "Gun" album)
        if not matches:
            # Try exact track match with any album for this artist
            for (a, al, t), paths in index.items():
                if a == norm_artist and t == norm_title:
                    matches.extend(paths)
            
            # Also try with extracted track names
            if not matches:
                title_tokens = set(norm_title.split())
                for (a, al, t), paths in index.items():
                    if a == norm_artist:
                        track_tokens = set(t.split())
                        # If all title tokens are in track name, it's a match
                        if title_tokens and title_tokens.issubset(track_tokens) and len(title_tokens) >= 2:
                            matches.extend(paths)
                        # Or if track tokens are subset of title (handles parenthetical content)
                        elif track_tokens.issubset(title_tokens) and len(track_tokens) >= 2:
                            matches.extend(paths)
                        # Or significant token overlap
                        elif title_tokens and track_tokens:
                            overlap = len(title_tokens & track_tokens)
                            min_len = min(len(title_tokens), len(track_tokens))
                            if min_len >= 2 and overlap >= (min_len * 2 // 3):
                                matches.extend(paths)
        
        # Strategy 7: Check Various Artists / Compilation albums
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
                        
                        # Also try with extracted track name
                        extracted_playlist_title = _extract_track_name_from_filename(title, artist)
                        if extracted_playlist_title != norm_title:
                            key_va_extracted = (norm_va, alt_album, extracted_playlist_title)
                            matches.extend(index.get(key_va_extracted, []))
                
                # If no album match, try just track name match in Various Artists
                if not matches:
                    for (a, al, t), paths in index.items():
                        if a == norm_va and t == norm_title:
                            matches.extend(paths)
                    
                    # Also try token-based matching
                    if not matches:
                        title_tokens = set(norm_title.split())
                        for (a, al, t), paths in index.items():
                            if a == norm_va:
                                track_tokens = set(t.split())
                                # If all title tokens are in track name, it's a match
                                if title_tokens and title_tokens.issubset(track_tokens) and len(title_tokens) >= 2:
                                    matches.extend(paths)
                                # Or if track tokens are subset of title
                                elif track_tokens.issubset(title_tokens) and len(track_tokens) >= 2:
                                    matches.extend(paths)
                
                # If we found matches, stop checking other VA variations
                if matches:
                    break
        
        # Remove duplicates while preserving order
        seen = set()
        unique_matches = []
        for p in matches:
            if p not in seen:
                seen.add(p)
                unique_matches.append(p)
        matches = unique_matches

        item: Dict[str, Any] = {
            "time": track.get("time"),
            "artist": artist,
            "album": album,
            "song": title,
            "match_status": "found" if matches else "missing",
            "matched_paths": [str(p) for p in matches],
        }

        if matches:
            found_count += 1
        elif include_candidates:
            # Candidate strategy:
            # - look within same (artist, album) if possible
            # - score by overlap between normalized strings
            aa_key = (_norm(artist), _norm(album))
            candidates = artist_album_to_paths.get(aa_key, [])

            # Simple similarity: track token overlap (cheap & decent)
            want_tokens = set(_norm(title).split())
            scored: List[Tuple[int, Path]] = []
            for p in candidates:
                have_tokens = set(_norm(p.stem).split())
                score = len(want_tokens & have_tokens)
                if score > 0:
                    scored.append((score, p))
            
            scored.sort(key=lambda x: x[0], reverse=True)
            item["candidate_paths"] = [str(p) for _score, p in scored[:max_candidates]]

        results.append(item)

    summary = {
        "library_root": str(library_root),
        "total_tracks": len(results),
        "found": found_count,
        "missing": len(results) - found_count,
    }

    return {
        "meta": data.get("meta", {}),
        "summary": summary,
        "results": results,
    }
