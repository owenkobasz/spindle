from __future__ import annotations

import re
import shutil
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from tqdm import tqdm
except ImportError:
    # Fallback if tqdm is not available
    def tqdm(iterable, *args, **kwargs):
        return iterable

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3NoHeaderError
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

# Reuse audio extensions from other modules
AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".aiff", ".aif", ".ogg", ".opus", ".alac"}

# Common image extensions for album artwork
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

# Common artwork filenames (case-insensitive)
ARTWORK_NAMES = {"cover", "folder", "album", "artwork", "front", "albumart"}

# Archive file extensions
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz"}


def _norm_for_matching(s: str) -> str:
    """
    Normalize strings for matching (same as match_playlist_to_library._norm).
    This ensures cataloged files can be matched correctly.
    """
    if s is None:
        return ""
    
    # Normalize unicode (e.g., "I'll" → "I'll" in many cases)
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


def _safe_filename(s: str, max_len: int = 180) -> str:
    """
    Make a filesystem-friendly filename chunk.
    
    This creates the actual directory/filename, but we also normalize
    for matching purposes to ensure consistency.
    """
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


def _find_archive_files(drop_location: Path) -> List[Path]:
    """Find all archive files (zip, etc.) in the drop location (recursively)."""
    archive_files = []
    
    if not drop_location.exists():
        return archive_files
    
    for path in drop_location.rglob("*"):
        if path.is_file() and path.suffix.lower() in ARCHIVE_EXTS:
            archive_files.append(path)
    
    return sorted(archive_files)


def _extract_zip_file(zip_path: Path, extract_to: Optional[Path] = None, 
                     show_progress: bool = True) -> Path:
    """
    Extract a zip file to a directory.
    
    Parameters
    ----------
    zip_path : Path
        Path to the zip file to extract
    extract_to : Path, optional
        Directory to extract to. If None, extracts to a directory with the same name
        as the zip file (without extension) in the same location.
    show_progress : bool
        If True, show a progress bar for extraction
    
    Returns
    -------
    Path to the extraction directory
    
    Raises
    ------
    zipfile.BadZipFile
        If the file is not a valid zip file
    """
    if extract_to is None:
        # Extract to a directory with the same name as the zip (without extension)
        extract_to = zip_path.parent / zip_path.stem
    
    # Create extraction directory if it doesn't exist
    extract_to.mkdir(parents=True, exist_ok=True)
    
    # Extract the zip file with progress bar
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        file_list = zip_ref.namelist()
        total_files = len(file_list)
        
        if show_progress and total_files > 0:
            # Show progress bar for extraction
            with tqdm(total=total_files, desc=f"  Extracting {zip_path.name}", 
                     unit="file", leave=False) as pbar:
                for member in file_list:
                    zip_ref.extract(member, extract_to)
                    pbar.update(1)
        else:
            # Extract all at once if no progress bar needed
            zip_ref.extractall(extract_to)
    
    return extract_to


def _extract_archives(drop_location: Path, remove_after_extract: bool = False, 
                     max_iterations: int = 10) -> List[Path]:
    """
    Find and extract all archive files in the drop location (recursively).
    
    This function will extract archives and then look for more archives in the
    extracted directories, up to max_iterations to handle nested archives.
    
    Parameters
    ----------
    drop_location : Path
        Directory to search for archive files
    remove_after_extract : bool
        If True, remove archive files after successful extraction
    max_iterations : int
        Maximum number of extraction passes (to handle nested archives)
    
    Returns
    -------
    List of Path objects for extracted directories
    """
    extracted_dirs = []
    iteration = 0
    
    while iteration < max_iterations:
        archive_files = _find_archive_files(drop_location)
        
        if not archive_files:
            # No more archives found, we're done
            break
        
        iteration += 1
        
        # Show progress for this iteration
        if iteration > 1:
            desc = f"Extracting nested archives (pass {iteration})"
        else:
            desc = "Extracting archives"
        
        new_extractions = []
        
        # Progress bar for archives in this iteration
        with tqdm(archive_files, desc=desc, unit="archive", leave=False) as archive_pbar:
            for archive_path in archive_pbar:
                archive_pbar.set_postfix(file=archive_path.name[:40])
                try:
                    # Only handle zip files for now (most common)
                    if archive_path.suffix.lower() == ".zip":
                        extract_dir = _extract_zip_file(archive_path, show_progress=True)
                        new_extractions.append(extract_dir)
                        extracted_dirs.append(extract_dir)
                        
                        # Optionally remove the zip file after extraction
                        if remove_after_extract:
                            archive_path.unlink()
                except (zipfile.BadZipFile, zipfile.LargeZipFile, Exception) as e:
                    # Skip invalid or problematic zip files
                    archive_pbar.write(f"  ⚠ Skipped {archive_path.name}: {str(e)[:50]}")
                    continue
        
        # If we didn't extract anything new, we're done
        if not new_extractions:
            break
    
    return extracted_dirs


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


def _find_artwork_files(source_dir: Path) -> List[Path]:
    """
    Find artwork files in a directory.
    
    Looks for common artwork filenames (cover.jpg, folder.jpg, etc.)
    or any image file in the directory.
    
    Parameters
    ----------
    source_dir : Path
        Directory to search for artwork files
    
    Returns
    -------
    List of Path objects for found artwork files
    """
    artwork_files = []
    
    if not source_dir.exists() or not source_dir.is_dir():
        return artwork_files
    
    # Build a case-insensitive mapping of existing files
    existing_files = {}
    for path in source_dir.iterdir():
        if path.is_file():
            existing_files[path.name.lower()] = path
    
    # First, look for common artwork filenames (case-insensitive)
    for artwork_name in ARTWORK_NAMES:
        for ext in IMAGE_EXTS:
            # Try lowercase first (most common)
            pattern_lower = (artwork_name + ext).lower()
            if pattern_lower in existing_files:
                artwork_files.append(existing_files[pattern_lower])
                break  # Found one, move to next artwork name
    
    # If no common names found, look for any image file
    if not artwork_files:
        for path in source_dir.iterdir():
            if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
                artwork_files.append(path)
                break  # Just take the first image file found
    
    return artwork_files


def _copy_artwork_files(source_dir: Path, dest_album_dir: Path, 
                        move_files: bool = True, skip_existing: bool = True) -> List[Path]:
    """
    Copy or move artwork files from source directory to destination album directory.
    
    Parameters
    ----------
    source_dir : Path
        Source directory containing artwork files
    dest_album_dir : Path
        Destination album directory in library
    move_files : bool
        If True, move files. If False, copy files.
    skip_existing : bool
        If True, skip artwork files that already exist in destination.
    
    Returns
    -------
    List of Path objects for successfully copied/moved artwork files
    """
    artwork_files = _find_artwork_files(source_dir)
    copied_files = []
    
    for artwork_path in artwork_files:
        try:
            dest_path = dest_album_dir / artwork_path.name
            
            # Check if artwork already exists
            if skip_existing and dest_path.exists():
                continue
            
            # Copy or move the artwork file
            if move_files:
                shutil.move(str(artwork_path), str(dest_path))
            else:
                shutil.copy2(str(artwork_path), str(dest_path))
            
            copied_files.append(dest_path)
        except Exception:
            # Silently skip artwork files that can't be copied
            # (e.g., permission errors, already moved, etc.)
            pass
    
    return copied_files


def _cleanup_drop_location(drop_location: Path) -> Dict[str, Any]:
    """
    Delete all files and empty directories from the drop location.
    
    This function safely removes all files and empty directories from the
    drop location after cataloging is complete.
    
    Parameters
    ----------
    drop_location : Path
        Directory to clean up
    
    Returns
    -------
    Dict with cleanup summary:
        - files_deleted: Number of files deleted
        - dirs_deleted: Number of directories deleted
        - errors: List of error messages
    """
    files_deleted = 0
    dirs_deleted = 0
    errors = []
    
    if not drop_location.exists() or not drop_location.is_dir():
        return {
            "files_deleted": 0,
            "dirs_deleted": 0,
            "errors": ["Drop location does not exist or is not a directory"]
        }
    
    # First, delete all files recursively
    for path in drop_location.rglob("*"):
        if path.is_file():
            try:
                path.unlink()
                files_deleted += 1
            except Exception as e:
                errors.append(f"Failed to delete {path}: {e}")
    
    # Then, delete empty directories (bottom-up, deepest first)
    # Get all directories, sort by depth (deepest first)
    dirs_to_check = []
    for path in drop_location.rglob("*"):
        if path.is_dir():
            # Calculate depth relative to drop_location
            depth = len(path.relative_to(drop_location).parts)
            dirs_to_check.append((depth, path))
    
    # Sort by depth descending (deepest first)
    dirs_to_check.sort(reverse=True, key=lambda x: x[0])
    
    # Delete empty directories
    for depth, dir_path in dirs_to_check:
        try:
            # Only delete if directory is empty
            if dir_path.exists() and not any(dir_path.iterdir()):
                dir_path.rmdir()
                dirs_deleted += 1
        except Exception as e:
            errors.append(f"Failed to delete directory {dir_path}: {e}")
    
    # Finally, try to delete the drop_location itself if it's empty
    # (but only if it's not the root drop_location - we'll leave that)
    # Actually, we should leave the drop_location itself, just clean its contents
    
    return {
        "files_deleted": files_deleted,
        "dirs_deleted": dirs_deleted,
        "errors": errors
    }


def catalog_music(
    drop_location: str | Path,
    library_root: str | Path,
    move_files: bool = True,
    skip_duplicates: bool = True,
    extract_archives: bool = True,
    remove_archives_after_extract: bool = False,
    cleanup_drop_location: bool = False,
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
    extract_archives : bool
        If True, automatically extract zip files found in drop location before cataloging.
    remove_archives_after_extract : bool
        If True, remove archive files after successful extraction. Only used if extract_archives=True.
    cleanup_drop_location : bool
        If True, delete all files and empty directories from drop location after cataloging.
        WARNING: This will permanently delete all files in the drop location!
    
    Returns
    -------
    Dict with summary of cataloging operation:
        - total_files: Total audio files found
        - cataloged: Number successfully cataloged
        - skipped: Number skipped (duplicates or errors)
        - errors: List of error messages
        - results: List of per-file results
        - cleanup: Dict with cleanup summary (if cleanup_drop_location=True)
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
    
    # Extract zip files if requested
    if extract_archives:
        archive_files = _find_archive_files(drop_path)
        if archive_files:
            extracted_dirs = _extract_archives(drop_path, remove_after_extract=remove_archives_after_extract)
            if extracted_dirs:
                # Progress bar will have already shown the extraction progress
                pass
    
    audio_files = _find_audio_files(drop_path)
    
    results = []
    cataloged = 0
    skipped = 0
    errors = []
    
    # Track which source album directories have had artwork processed
    # Key: (source_dir, dest_album_dir), Value: True if processed
    processed_artwork_dirs = set()
    
    progress_bar = tqdm(audio_files, desc="Cataloging files", unit="file")
    for file_path in progress_bar:
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
                    # Print skip message
                    progress_bar.write(f"  ⏭  Skipped: {file_path.name} (duplicate)")
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
            action = "Moving" if move_files else "Copying"
            progress_bar.write(f"  {action}: {file_path.name}")
            progress_bar.write(f"      → {dest_path.relative_to(library_path)}")
            
            if move_files:
                shutil.move(str(file_path), str(dest_path))
            else:
                shutil.copy2(str(file_path), str(dest_path))
            
            # Process artwork files from the source album directory
            # Only process once per source album directory
            source_album_dir = file_path.parent
            artwork_key = (str(source_album_dir), str(album_dir))
            
            if artwork_key not in processed_artwork_dirs:
                copied_artwork = _copy_artwork_files(
                    source_album_dir, 
                    album_dir, 
                    move_files=move_files,
                    skip_existing=skip_duplicates
                )
                if copied_artwork:
                    progress_bar.write(f"  📷 Artwork: {len(copied_artwork)} file(s) → {album_dir.relative_to(library_path)}")
                processed_artwork_dirs.add(artwork_key)
            
            result["status"] = "cataloged"
            result["destination_path"] = str(dest_path)
            cataloged += 1
            
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            errors.append(f"{file_path}: {e}")
            skipped += 1
            # Print error message
            progress_bar.write(f"  ✗ Error: {file_path.name} - {str(e)}")
        
        results.append(result)
    
    # Cleanup drop location if requested
    cleanup_summary = None
    if cleanup_drop_location:
        print("\nCleaning up drop location...")
        cleanup_summary = _cleanup_drop_location(drop_path)
        if cleanup_summary["files_deleted"] > 0 or cleanup_summary["dirs_deleted"] > 0:
            print(f"  Deleted {cleanup_summary['files_deleted']} file(s) and {cleanup_summary['dirs_deleted']} directory(ies)")
        if cleanup_summary["errors"]:
            print(f"  ⚠ {len(cleanup_summary['errors'])} error(s) during cleanup")
    
    result_dict = {
        "total_files": len(audio_files),
        "cataloged": cataloged,
        "skipped": skipped,
        "errors": errors,
        "results": results,
    }
    
    if cleanup_summary is not None:
        result_dict["cleanup"] = cleanup_summary
    
    return result_dict

