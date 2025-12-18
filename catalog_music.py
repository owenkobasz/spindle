from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3NoHeaderError
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

# Reuse audio extensions from other modules
AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".aiff", ".aif", ".ogg", ".opus", ".alac"}


def _safe_filename(s: str, max_len: int = 180) -> str:
    """Make a filesystem-friendly filename chunk."""
    s = s or "unknown"
    s = unicodedata.normalize("NFKD", s)
    s = s.replace("/", "-")
    s = re.sub(r"[\s]+", " ", s).strip()
    s = re.sub(r'[<>:"\\|?*\x00-\x1f]', "", s)  # unsafe chars
    return s[:max_len].strip() or "unknown"


def _get_first_tag_value(tags: Any, *keys: str) -> Optional[str]:
    """Extract first value from mutagen tags, trying multiple keys."""
    if not tags:
        return None
    
    for key in keys:
        try:
            value = tags.get(key)
            if value:
                # Mutagen returns lists for some tags
                if isinstance(value, list):
                    value = value[0]
                if isinstance(value, str):
                    return value.strip()
                # Some tags return objects with text attribute
                if hasattr(value, 'text'):
                    return str(value.text[0] if isinstance(value.text, list) else value.text).strip()
                return str(value).strip()
        except (AttributeError, KeyError, IndexError, TypeError):
            continue
    return None


def _extract_metadata_from_file(file_path: Path) -> Dict[str, Optional[str]]:
    """
    Extract metadata from an audio file using mutagen.
    
    Returns:
        Dict with keys: artist, album, title, tracknumber
    """
    metadata = {
        "artist": None,
        "album": None,
        "title": None,
        "tracknumber": None,
    }
    
    if not MUTAGEN_AVAILABLE:
        return metadata
    
    try:
        audio_file = MutagenFile(str(file_path))
        if audio_file is None:
            return metadata
        
        tags = audio_file.tags
        if not tags:
            return metadata
        
        # Try various tag formats for artist
        artist = _get_first_tag_value(
            tags,
            "TPE1",  # ID3v2.3/2.4
            "ARTIST",  # Vorbis/FLAC
            "\xa9ART",  # iTunes/M4A
            "TPE2",  # Album Artist (fallback)
        )
        metadata["artist"] = artist
        
        # Try various tag formats for album
        album = _get_first_tag_value(
            tags,
            "TALB",  # ID3v2.3/2.4
            "ALBUM",  # Vorbis/FLAC
            "\xa9alb",  # iTunes/M4A
        )
        metadata["album"] = album
        
        # Try various tag formats for title
        title = _get_first_tag_value(
            tags,
            "TIT2",  # ID3v2.3/2.4
            "TITLE",  # Vorbis/FLAC
            "\xa9nam",  # iTunes/M4A
        )
        metadata["title"] = title
        
        # Try various tag formats for track number
        tracknum = _get_first_tag_value(
            tags,
            "TRCK",  # ID3v2.3/2.4
            "TRACKNUMBER",  # Vorbis/FLAC
            "trkn",  # iTunes/M4A
        )
        if tracknum:
            # Extract just the number (e.g., "1/10" -> "1")
            match = re.search(r'\d+', str(tracknum))
            if match:
                metadata["tracknumber"] = match.group(0)
        
    except (ID3NoHeaderError, Exception):
        # File has no tags or error reading tags
        pass
    
    return metadata


def _infer_metadata_from_path(file_path: Path) -> Dict[str, Optional[str]]:
    """
    Infer metadata from file path and filename when tags are missing.
    
    Handles common patterns like:
    - Artist/Album/Track.ext
    - Artist - Track.ext
    - Album/Track.ext
    - Track.ext
    """
    metadata = {
        "artist": None,
        "album": None,
        "title": None,
        "tracknumber": None,
    }
    
    # Get path parts (excluding the file itself)
    parts = list(file_path.parent.parts)
    filename_stem = file_path.stem
    
    # Remove track number prefix if present (e.g., "01. Track Name" -> "Track Name")
    track_match = re.match(r'^(\d+)\.?\s*(.+)$', filename_stem)
    if track_match:
        metadata["tracknumber"] = track_match.group(1)
        filename_stem = track_match.group(2)
    
    # Try to extract artist and title from filename (e.g., "Artist - Title")
    title_match = re.match(r'^(.+?)\s*[-–—]\s*(.+)$', filename_stem)
    if title_match:
        metadata["artist"] = title_match.group(1).strip()
        metadata["title"] = title_match.group(2).strip()
    else:
        metadata["title"] = filename_stem
    
    # If we have path parts, try to infer structure
    # Common: Artist/Album/Track or Album/Track
    if len(parts) >= 2:
        # Assume last two parts are Artist and Album
        metadata["artist"] = parts[-2] if not metadata["artist"] else metadata["artist"]
        metadata["album"] = parts[-1]
    elif len(parts) == 1:
        # Single directory - could be Artist or Album
        if not metadata["artist"]:
            metadata["artist"] = parts[0]
        elif not metadata["album"]:
            metadata["album"] = parts[0]
    
    return metadata


def _merge_metadata(tag_metadata: Dict[str, Optional[str]], 
                   inferred_metadata: Dict[str, Optional[str]]) -> Dict[str, str]:
    """
    Merge tag metadata with inferred metadata, preferring tags when available.
    
    Returns:
        Dict with guaranteed string values (using "Unknown" as fallback)
    """
    result = {}
    
    for key in ["artist", "album", "title", "tracknumber"]:
        value = tag_metadata.get(key) or inferred_metadata.get(key)
        if value:
            result[key] = str(value).strip()
        else:
            # Use appropriate defaults
            if key == "tracknumber":
                result[key] = ""  # Empty string for track number
            elif key == "album":
                result[key] = "Unknown Album"
            elif key == "artist":
                result[key] = "Unknown Artist"
            else:  # title
                result[key] = "Unknown Track"
    
    return result


def _find_audio_files(drop_location: Path) -> List[Path]:
    """Find all audio files in the drop location (recursively)."""
    audio_files = []
    
    if not drop_location.exists():
        return audio_files
    
    for path in drop_location.rglob("*"):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS:
            audio_files.append(path)
    
    return sorted(audio_files)


def _check_duplicate(library_root: Path, artist: str, album: str, title: str, 
                     file_path: Path) -> Optional[Path]:
    """
    Check if a file with the same artist/album/title already exists in library.
    
    Returns:
        Path to existing file if duplicate found, None otherwise
    """
    artist_dir = library_root / _safe_filename(artist)
    if not artist_dir.exists():
        return None
    
    album_dir = artist_dir / _safe_filename(album)
    if not album_dir.exists():
        return None
    
    # Check for files with similar names (normalize for comparison)
    target_stem = _safe_filename(title)
    for existing_file in album_dir.iterdir():
        if existing_file.is_file() and existing_file.suffix.lower() in AUDIO_EXTS:
            existing_stem = existing_file.stem
            # Remove track numbers for comparison
            existing_clean = re.sub(r'^\d+\.?\s*', '', existing_stem)
            target_clean = re.sub(r'^\d+\.?\s*', '', target_stem)
            
            # Simple comparison (case-insensitive)
            if existing_clean.lower() == target_clean.lower():
                return existing_file
    
    return None


def catalog_music(
    drop_location: str | Path,
    library_root: str | Path,
    move_files: bool = True,
    skip_duplicates: bool = True,
) -> Dict[str, Any]:
    """
    Catalog music files from a drop location into the library.
    
    Parameters
    ----------
    drop_location : str|Path
        Directory where newly downloaded music files are located
    library_root : str|Path
        Root directory of the music library (where Artist/Album/Track structure lives)
    move_files : bool
        If True, move files to library. If False, copy files.
    skip_duplicates : bool
        If True, skip files that already exist in library. If False, allow duplicates.
    
    Returns
    -------
    Dict with summary of cataloging operation:
        - total_files: Total audio files found
        - cataloged: Number successfully cataloged
        - skipped: Number skipped (duplicates or errors)
        - errors: List of error messages
        - results: List of per-file results
    """
    drop_path = Path(drop_location).expanduser().resolve()
    library_path = Path(library_root).expanduser().resolve()
    
    if not drop_path.exists():
        raise FileNotFoundError(f"Drop location does not exist: {drop_path}")
    
    if not library_path.exists():
        raise FileNotFoundError(f"Library root does not exist: {library_path}")
    
    if not MUTAGEN_AVAILABLE:
        raise ImportError(
            "mutagen is required for cataloging. Install it with: pip install mutagen"
        )
    
    audio_files = _find_audio_files(drop_path)
    
    results = []
    cataloged = 0
    skipped = 0
    errors = []
    
    for file_path in audio_files:
        result = {
            "source_path": str(file_path),
            "status": "pending",
            "destination_path": None,
            "error": None,
        }
        
        try:
            # Extract metadata
            tag_metadata = _extract_metadata_from_file(file_path)
            inferred_metadata = _infer_metadata_from_path(file_path)
            metadata = _merge_metadata(tag_metadata, inferred_metadata)
            
            artist = metadata["artist"]
            album = metadata["album"]
            title = metadata["title"]
            tracknum = metadata.get("tracknumber", "")
            
            # Check for duplicates
            if skip_duplicates:
                duplicate = _check_duplicate(library_path, artist, album, title, file_path)
                if duplicate:
                    result["status"] = "skipped"
                    result["error"] = f"Duplicate found: {duplicate}"
                    skipped += 1
                    results.append(result)
                    continue
            
            # Build destination path: Library/Artist/Album/Track.ext
            artist_dir = library_path / _safe_filename(artist)
            album_dir = artist_dir / _safe_filename(album)
            album_dir.mkdir(parents=True, exist_ok=True)
            
            # Build filename with optional track number
            if tracknum:
                filename = f"{tracknum.zfill(2)}. {_safe_filename(title)}{file_path.suffix}"
            else:
                filename = f"{_safe_filename(title)}{file_path.suffix}"
            
            dest_path = album_dir / filename
            
            # Handle existing file at destination
            if dest_path.exists():
                # Add a counter to make it unique
                counter = 1
                base_name = dest_path.stem
                while dest_path.exists():
                    dest_path = album_dir / f"{base_name} ({counter}){file_path.suffix}"
                    counter += 1
            
            # Move or copy file
            if move_files:
                shutil.move(str(file_path), str(dest_path))
            else:
                shutil.copy2(str(file_path), str(dest_path))
            
            result["status"] = "cataloged"
            result["destination_path"] = str(dest_path)
            cataloged += 1
            
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            errors.append(f"{file_path}: {e}")
            skipped += 1
        
        results.append(result)
    
    return {
        "total_files": len(audio_files),
        "cataloged": cataloged,
        "skipped": skipped,
        "errors": errors,
        "results": results,
    }

