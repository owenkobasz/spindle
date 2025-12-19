#!/usr/bin/env python3
"""
Spindle - Main Entry Point

This script provides an interactive workflow to:
1. Scrape a playlist from a URL
2. Match tracks against your local music library
3. Create a playlist folder with numbered tracks
"""

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import requests
from tqdm import tqdm

from scraper import playlist_scraper
from match_playlist_to_library import match_playlist_to_library
from create_playlist import export_playlist_copies
from link_finder import TrackMeta, find_share_urls_from_metadata
from catalog_music import catalog_music


# ----------------------------
# Artifacts and JSON utilities
# ----------------------------

ARTIFACTS_DIR = Path("artifacts")
SETTINGS_FILE = Path("spindle_settings.json")


# ----------------------------
# Settings management
# ----------------------------

DEFAULT_SETTINGS = {
    "library": {
        "base_folder": "/Volumes/Music Library",
        "library_subpath": ""
    },
    "streaming_service": "amazon_music",  # "amazon_music" or "tidal"
    "catalog": {
        "drop_location": "",
        "move_files": True,
        "skip_duplicates": True
    },
    "export": {
        "default_target_dir": ""
    }
}


def load_settings() -> dict:
    """
    Load settings from file, returning defaults if file doesn't exist.
    
    Returns:
        Settings dictionary with defaults merged
    """
    if not SETTINGS_FILE.exists():
        return DEFAULT_SETTINGS.copy()
    
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            user_settings = json.load(f)
        
        # Merge with defaults to ensure all keys exist
        settings = DEFAULT_SETTINGS.copy()
        settings.update(user_settings)
        
        # Deep merge nested dictionaries
        if "library" in user_settings:
            settings["library"].update(user_settings["library"])
        if "catalog" in user_settings:
            settings["catalog"].update(user_settings["catalog"])
        if "export" in user_settings:
            settings["export"].update(user_settings["export"])
        
        return settings
    except Exception as e:
        print(f"Warning: Could not load settings: {e}")
        print("Using default settings.")
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    """
    Save settings to file.
    
    Args:
        settings: Settings dictionary to save
    """
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving settings: {e}")


def get_setting(key_path: str, default=None) -> any:
    """
    Get a setting value using dot notation (e.g., "library.base_folder").
    
    Args:
        key_path: Dot-separated path to setting (e.g., "library.base_folder")
        default: Default value if setting not found
    
    Returns:
        Setting value or default
    """
    settings = load_settings()
    keys = key_path.split('.')
    value = settings
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value if value != "" else default


def set_setting(key_path: str, value: any) -> None:
    """
    Set a setting value using dot notation and save to file.
    
    Args:
        key_path: Dot-separated path to setting (e.g., "library.base_folder")
        value: Value to set
    """
    settings = load_settings()
    keys = key_path.split('.')
    
    # Navigate to the parent dict
    current = settings
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    
    # Set the value
    current[keys[-1]] = value
    
    # Save
    save_settings(settings)


def safe_slug(text: str) -> str:
    """
    Convert text to a filesystem-safe slug.
    
    Args:
        text: Text to convert to slug
    
    Returns:
        Lowercase slug with alphanumeric characters and dashes only
    """
    if not text:
        return "unknown"
    
    # Normalize to lowercase
    slug = text.lower()
    
    # Replace spaces and common separators with dashes
    slug = re.sub(r'[\s_]+', '-', slug)
    
    # Keep only alphanumeric and dashes
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    
    # Collapse multiple dashes
    slug = re.sub(r'-+', '-', slug)
    
    # Strip leading/trailing dashes
    slug = slug.strip('-')
    
    return slug or "unknown"


def extract_stem_from_playlist_path(playlist_path: Path) -> str:
    """
    Extract the artifact stem from a playlist JSON file path.
    
    This ensures consistent naming across playlist, match, and enriched files.
    For example: "running-redlights.playlist.json" -> "running-redlights"
    
    Args:
        playlist_path: Path to playlist JSON file
    
    Returns:
        Stem extracted from filename (without .playlist.json suffix)
    """
    stem = playlist_path.stem  # Gets "name.playlist" from "name.playlist.json"
    
    # Remove .playlist suffix if present
    if stem.endswith(".playlist"):
        stem = stem[:-9]  # Remove ".playlist"
    
    return stem


def extract_stem_from_artifact_path(artifact_path: Path) -> str:
    """
    Extract the base artifact stem from any artifact file path (playlist, match, or enriched).
    
    This ensures consistent naming across all artifact types.
    For example: 
    - "running-redlights.playlist.json" -> "running-redlights"
    - "running-redlights.match.json" -> "running-redlights"
    - "running-redlights.enriched.json" -> "running-redlights"
    
    Args:
        artifact_path: Path to any artifact JSON file
    
    Returns:
        Base stem extracted from filename (without type suffix)
    """
    stem = artifact_path.stem  # Gets "name.type" from "name.type.json"
    
    # Remove type suffixes if present
    if stem.endswith(".playlist"):
        stem = stem[:-9]  # Remove ".playlist"
    elif stem.endswith(".match"):
        stem = stem[:-6]  # Remove ".match"
    elif stem.endswith(".enriched"):
        stem = stem[:-9]  # Remove ".enriched"
    
    return stem


def derive_artifact_stem(meta: dict, custom_name: str = None) -> str:
    """
    Derive an artifact filename stem from playlist metadata.
    
    Args:
        meta: Playlist metadata dict
        custom_name: Optional custom name to use instead of auto-generated slug
    
    Returns:
        Stem like "2025-12-17_lady-love" (auto-generated) or "custom-name" (when custom_name provided)
    """
    # Use custom name if provided (without date prefix)
    if custom_name:
        slug = safe_slug(custom_name)
        return slug
    
    # Extract date from fetched_at_utc (YYYY-MM-DD)
    date_str = ""
    fetched_at = meta.get("fetched_at_utc", "")
    if isinstance(fetched_at, str) and len(fetched_at) >= 10:
        date_str = fetched_at[:10]
    else:
        # Fallback to today's date
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Extract slug from canonical_url or page_title
    slug = ""
    canonical = meta.get("canonical_url", "")
    if canonical:
        # Extract slug from URL (e.g., "https://playlists.wprb.com/WPRB/pl/21686552/Lady-Love" -> "lady-love")
        parts = canonical.rstrip('/').split('/')
        if parts:
            slug = safe_slug(parts[-1])
    
    if not slug:
        title = meta.get("page_title") or meta.get("playlist_title", "")
        slug = safe_slug(title)
    
    if not slug:
        slug = "playlist"
    
    return f"{date_str}_{slug}"


def load_json(path: Path) -> dict:
    """
    Load JSON from a file path.
    
    Args:
        path: Path to JSON file
    
    Returns:
        Parsed JSON dict
    
    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(obj: dict, path: Path) -> Path:
    """
    Save a dict to JSON file.
    
    Args:
        obj: Dict to save
        path: Path to save to
    
    Returns:
        Path to saved file
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    
    return path


def print_separator(char="=", length=60):
    """Print a visual separator line."""
    print(char * length)


def print_title(text: str, char="=", length=60):
    """
    Print a centered title with separators above and below.
    
    Args:
        text: Text to center
        char: Character to use for separator (default: "=")
        length: Length of separator line (default: 60)
    """
    print_separator(char, length)
    # Center the text within the separator length
    padding = (length - len(text)) // 2
    print(" " * padding + text)
    print_separator(char, length)

def print_banner():
    banner = r"""
   ███████╗██████╗ ██╗███╗   ██╗██████╗ ██╗     ███████╗
   ██╔════╝██╔══██╗██║████╗  ██║██╔══██╗██║     ██╔════╝
   ███████╗██████╔╝██║██╔██╗ ██║██║  ██║██║     █████╗  
   ╚════██║██╔═══╝ ██║██║╚██╗██║██║  ██║██║     ██╔══╝  
   ███████║██║     ██║██║ ╚████║██████╔╝███████╗███████╗
   ╚══════╝╚═╝     ╚═╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚══════╝

            curated radio → local playlists
"""
    print(banner)

def prompt_user(prompt: str, default: str = None) -> str:
    """
    Prompt user for input with optional default value.
    
    Returns the user's input (or default if provided and user just presses Enter).
    """
    if default:
        full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "
    
    response = input(full_prompt).strip()
    return response if response else (default or "")


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """
    Prompt user for yes/no confirmation.
    
    Args:
        prompt: The question to ask
        default: Default value if user just presses Enter
    
    Returns:
        True for yes, False for no
    """
    default_str = "Y/n" if default else "y/N"
    response = input(f"{prompt} [{default_str}]: ").strip().lower()
    
    if not response:
        return default
    
    return response in ("y", "yes")


def get_library_path() -> tuple[str, str]:
    """
    Get library location from settings if valid, otherwise prompt user.
    
    Returns:
        Tuple of (base_folder, library_subpath)
    """
    # Get settings
    base = get_setting("library.base_folder", "/Volumes/Music Library")
    subpath = get_setting("library.library_subpath", "")
    
    # Check if base folder exists and is valid
    base_path = Path(base).expanduser()
    if base_path.exists():
        # Settings are valid, use them silently
        return str(base_path), subpath
    
    # Settings invalid or missing, prompt user
    print_title("LIBRARY LOCATION")
    print("Enter the path to your music library.")
    print("Press Enter to use the saved default, or enter a different path.")
    print()
    
    base = prompt_user("Base folder", base)
    if not base:
        # If user cleared the default, use it anyway
        base = get_setting("library.base_folder", "/Volumes/Music Library")
    
    # Check if base folder exists
    base_path = Path(base).expanduser()
    if not base_path.exists():
        print(f"Error: Base folder does not exist: {base_path}")
        sys.exit(1)
    
    # Ask for subpath if base might not be the library root
    subpath = prompt_user("Library subpath (press Enter if base folder IS the library)", subpath)
    
    # Save to settings
    set_setting("library.base_folder", base)
    set_setting("library.library_subpath", subpath)
    
    return str(base_path), subpath


def print_track_list(tracks: list[dict], title: str = "TRACK LIST") -> None:
    """
    Print a formatted list of tracks.
    
    Args:
        tracks: List of track dictionaries with 'artist' and 'song' keys
        title: Title to display above the track list
    """
    if not tracks:
        return
    
    print_title(title)
    for i, track in enumerate(tracks, 1):
        artist = track.get('artist', 'Unknown Artist')
        song = track.get('song', 'Unknown Song')
        print(f"  {i:3d}. {artist} - {song}")
    print()


def print_track_list_with_links(tracks: list[dict], title: str = "ENRICHED TRACKS") -> None:
    """
    Print a formatted list of tracks with their streaming links.
    
    Args:
        tracks: List of track dictionaries with 'artist', 'song', and 'share_links' keys
        title: Title to display above the track list
    """
    if not tracks:
        return
    
    print_title(title)
    for i, track in enumerate(tracks, 1):
        artist = track.get('artist', 'Unknown Artist')
        song = track.get('song', 'Unknown Song')
        print(f"  {i:3d}. {artist} - {song}")
        
        # Get share links
        share_links = track.get('share_links', {})
        album_links = track.get('album_share_links', {})
        
        # Print track links (prioritize Amazon Music, then show others)
        if share_links:
            # Try Amazon Music first
            if 'amazon_music' in share_links:
                print(f"       Track: {share_links['amazon_music']}")
            # Show other services if Amazon Music not available
            elif share_links:
                # Show first available link
                service, url = next(iter(share_links.items()))
                service_name = service.replace('_', ' ').title()
                print(f"       Track ({service_name}): {url}")
        else:
            print(f"       Track: (no links found)")
        
        # Print album links (prioritize Amazon Music, then show others)
        if album_links:
            # Try Amazon Music first
            if 'amazon_music' in album_links:
                print(f"       Album: {album_links['amazon_music']}")
            # Show other services if Amazon Music not available
            elif album_links:
                # Show first available link
                service, url = next(iter(album_links.items()))
                service_name = service.replace('_', ' ').title()
                print(f"       Album ({service_name}): {url}")
        else:
            # Check if there's album info but no links
            if track.get('album'):
                print(f"       Album: (no links found)")
        
        print()
    print()


def print_album_links_summary(tracks: list[dict], title: str = "ALBUM LINKS SUMMARY") -> None:
    """
    Print a summary of all unique album links found in the tracks.
    
    Args:
        tracks: List of track dictionaries with 'album_share_links' keys
        title: Title to display above the album links list
    """
    if not tracks:
        return
    
    # Collect unique album links, prioritizing Amazon Music
    album_links_map = {}  # Maps (artist, album) -> {service: url}
    
    for track in tracks:
        album_links = track.get('album_share_links', {})
        if not album_links:
            continue
        
        artist = track.get('artist', 'Unknown Artist')
        album = track.get('album', 'Unknown Album')
        key = (artist, album)
        
        # Store links for this album (prioritize Amazon Music if available)
        if key not in album_links_map:
            album_links_map[key] = {}
        
        # Prefer Amazon Music, but store all available services
        if 'amazon_music' in album_links:
            album_links_map[key]['amazon_music'] = album_links['amazon_music']
        else:
            # Store first available service
            for service, url in album_links.items():
                if service not in album_links_map[key]:
                    album_links_map[key][service] = url
                    break
    
    if not album_links_map:
        return
    
    print_title(title)
    
    # Sort by artist, then album
    sorted_albums = sorted(album_links_map.items(), key=lambda x: (x[0][0].lower(), x[0][1].lower()))
    
    for i, ((artist, album), links) in enumerate(sorted_albums, 1):
        #print(f"  {i:3d}. {artist} - {album}")
        
        # Print links (prioritize Amazon Music)
        if 'amazon_music' in links:
            print(f"{links['amazon_music']}")
        elif links:
            # Show first available service
            service, url = next(iter(links.items()))
            service_name = service.replace('_', ' ').title()
            print(f"       ({service_name}) {url}")
        
        #print()
    print()


def display_missing_tracks(match_result: dict) -> list[dict]:
    """
    Display missing tracks and return list of missing track info.
    Includes Amazon Music links for tracks and albums when available.
    
    Returns:
        List of track dictionaries that are missing
    """
    missing = [r for r in match_result["results"] if r["match_status"] == "missing"]
    
    if not missing:
        return []
    
    print_title(f"MISSING TRACKS ({len(missing)} of {match_result['summary']['total_tracks']})")
    print("Fetching Amazon Music links...")
    print()
    
    # Create a session for API calls
    session = requests.Session()
    
    try:
        for i, track in enumerate(missing, 1):
            print(f"{i}. {track['artist']} - {track['song']}")
            if track.get('album'):
                print(f"   Album: {track['album']}")
            
            # Fetch links for this track
            try:
                track_meta = TrackMeta(
                    artist=track.get('artist', ''),
                    title=track.get('song', ''),
                    album=track.get('album')
                )
                link_result = find_share_urls_from_metadata(
                    track_meta,
                    session=session,
                    use_cache=True
                )
                
                # Display Amazon Music links if available
                if link_result.get('ok'):
                    # Track link
                    track_amazon = link_result.get('aggregated', {}).get('targets', {}).get('amazon_music')
                    if track_amazon:
                        print(f"   Track: {track_amazon}")
                    
                    # Album link (derived from track link by removing query string)
                    album_amazon = None
                    if link_result.get('album_aggregated'):
                        album_amazon = link_result.get('album_aggregated', {}).get('targets', {}).get('amazon_music')
                    if album_amazon:
                        print(f"   Album: {album_amazon}")
                    
                    # If no Amazon links found, indicate that
                    if not track_amazon and not album_amazon:
                        print(f"   (Amazon Music links not available)")
                else:
                    print(f"   (Could not find links)")
            except Exception as e:
                # Silently handle errors - just don't show links
                print(f"   (Error fetching links)")
            
            if track.get('candidate_paths'):
                print(f"   Candidates found:")
                for path in track['candidate_paths'][:3]:  # Show first 3 candidates
                    print(f"     - {Path(path).name}")
            print()
    
    finally:
        session.close()
    
    return missing


def create_artist_directories(missing_tracks: list[dict], library_root: Path) -> None:
    """
    Create artist directories in the library for all missing tracks.
    
    Args:
        missing_tracks: List of track dictionaries that are missing
        library_root: Path to the library root directory
    """
    if not missing_tracks:
        return
    
    # Get unique artists from missing tracks
    artists = set()
    for track in missing_tracks:
        artist = track.get('artist', '').strip()
        if artist:
            artists.add(artist)
    
    if not artists:
        return
    
    print_title("CREATE ARTIST DIRECTORIES")
    print(f"Found {len(artists)} unique artists with missing tracks:")
    for artist in sorted(artists):
        print(f"  - {artist}")
    print()
    
    if not prompt_yes_no("Create artist directories in library?", default=True):
        return
    
    created = []
    skipped = []
    
    for artist in sorted(artists):
        artist_dir = library_root / artist
        if artist_dir.exists():
            skipped.append(artist)
            continue
        
        try:
            artist_dir.mkdir(parents=True, exist_ok=True)
            created.append(artist)
            print(f"✓ Created: {artist_dir}")
        except Exception as e:
            print(f"✗ Error creating {artist_dir}: {e}")
    
    print()
    if created:
        print(f"✓ Created {len(created)} artist directories")
    if skipped:
        print(f"ℹ {len(skipped)} artist directories already exist")
    print()


def catalog_new_music(base_folder: str, library_subpath: str) -> None:
    """
    Catalog newly downloaded music from a drop location into the library.
    
    Args:
        base_folder: Base folder containing the library
        library_subpath: Subpath to the library within base_folder
    """
    # Get settings
    drop_location = get_setting("catalog.drop_location", "")
    move_files = get_setting("catalog.move_files", True)
    skip_duplicates = get_setting("catalog.skip_duplicates", True)
    
    # Check if drop location is valid
    drop_path = None
    if drop_location:
        drop_path = Path(drop_location).expanduser()
        if not drop_path.exists():
            drop_path = None
    
    # If all settings are valid, use them silently
    if drop_path:
        print_title("CATALOG NEW MUSIC")
        print(f"Using saved settings:")
        print(f"  Drop location: {drop_path}")
        print(f"  Move files: {move_files}")
        print(f"  Skip duplicates: {skip_duplicates}")
        print()
    else:
        # Settings invalid or missing, prompt user
        print_title("CATALOG NEW MUSIC")
        print("This will scan a drop location for music files and organize them")
        print("into your library structure (Artist/Album/Track).")
        print()
        
        drop_location = prompt_user("Enter drop location (where new music files are)", drop_location)
        if not drop_location:
            print("Error: Drop location is required.")
            sys.exit(1)
        
        drop_path = Path(drop_location).expanduser()
        if not drop_path.exists():
            print(f"Error: Drop location does not exist: {drop_path}")
            sys.exit(1)
        
        # Save drop location to settings
        set_setting("catalog.drop_location", drop_location)
        
        # Get preferences from settings
        default_move = get_setting("catalog.move_files", True)
        default_skip = get_setting("catalog.skip_duplicates", True)
        
        # Ask about move vs copy
        move_files = prompt_yes_no("Move files to library? (No = copy files)", default=default_move)
        
        # Ask about duplicates
        skip_duplicates = prompt_yes_no("Skip files that already exist in library?", default=default_skip)
        
        # Save preferences if changed
        if move_files != default_move:
            set_setting("catalog.move_files", move_files)
        if skip_duplicates != default_skip:
            set_setting("catalog.skip_duplicates", skip_duplicates)
    
    # Calculate library root path
    library_root_path = Path(base_folder)
    if library_subpath:
        library_root_path = library_root_path / library_subpath
    library_root_path = library_root_path.resolve()
    
    if not library_root_path.exists():
        print(f"Error: Library root does not exist: {library_root_path}")
        sys.exit(1)
    
    print()
    print("Scanning for audio files...")
    
    try:
        result = catalog_music(
            drop_location=str(drop_path),
            library_root=str(library_root_path),
            move_files=move_files,
            skip_duplicates=skip_duplicates,
        )
        
        print_separator()
        print_title("CATALOGING COMPLETE")
        print_separator()
        print(f"Total files found: {result['total_files']}")
        print(f"✓ Cataloged: {result['cataloged']}")
        print(f"ℹ Skipped: {result['skipped']}")
        
        if result['errors']:
            print()
            print(f"⚠ {len(result['errors'])} errors occurred:")
            for error in result['errors'][:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(result['errors']) > 10:
                print(f"  ... and {len(result['errors']) - 10} more errors")
        
        print()
        
        # Show some examples of cataloged files
        cataloged_files = [r for r in result['results'] if r['status'] == 'cataloged']
        if cataloged_files:
            print("Sample of cataloged files:")
            for item in cataloged_files[:5]:
                print(f"  ✓ {Path(item['source_path']).name} → {Path(item['destination_path']).relative_to(library_root_path)}")
            if len(cataloged_files) > 5:
                print(f"  ... and {len(cataloged_files) - 5} more")
            print()
        
        if result['cataloged'] > 0:
            print("✓ Music successfully cataloged into library!")
        else:
            print("ℹ No files were cataloged (all skipped or errors occurred).")
        
    except ImportError as e:
        print(f"Error: {e}")
        print("Please install mutagen: pip install mutagen")
        sys.exit(1)
    except Exception as e:
        print(f"Error cataloging music: {e}")
        sys.exit(1)


def confirm_skip_tracks(still_missing: list[dict]) -> list[dict]:
    """
    Ask user to confirm skipping each track that still can't be found.
    Includes Amazon Music links for tracks and albums when available.
    
    Args:
        still_missing: List of tracks that are still missing after re-matching
    
    Returns:
        List of tracks that user confirmed to skip
    """
    if not still_missing:
        return []
    
    print_title("CONFIRM SKIPPING TRACKS")
    print(f"The following {len(still_missing)} tracks still cannot be found:")
    print("You can choose to skip each track or cancel the operation.")
    print()
    
    tracks_to_skip = []
    tracks_to_keep = []
    
    # Create a session for API calls
    session = requests.Session()
    
    try:
        for i, track in enumerate(still_missing, 1):
            artist = track.get('artist', 'Unknown')
            song = track.get('song', 'Unknown')
            album = track.get('album', '')
            
            print(f"{i}/{len(still_missing)}. {artist} - {song}")
            if album:
                print(f"    Album: {album}")
            
            # Fetch links for this track
            try:
                track_meta = TrackMeta(
                    artist=track.get('artist', ''),
                    title=track.get('song', ''),
                    album=track.get('album')
                )
                link_result = find_share_urls_from_metadata(
                    track_meta,
                    session=session,
                    use_cache=True
                )
                
                # Display Amazon Music links if available
                if link_result.get('ok'):
                    # Track link
                    track_amazon = link_result.get('aggregated', {}).get('targets', {}).get('amazon_music')
                    if track_amazon:
                        print(f"    Track: {track_amazon}")
                    
                    # Album link (derived from track link by removing query string)
                    album_amazon = None
                    if link_result.get('album_aggregated'):
                        album_amazon = link_result.get('album_aggregated', {}).get('targets', {}).get('amazon_music')
                    if album_amazon:
                        print(f"    Album: {album_amazon}")
            except Exception:
                # Silently handle errors - just don't show links
                pass
            
            if prompt_yes_no("    Skip this track?", default=False):
                tracks_to_skip.append(track)
                print("    → Will be skipped")
            else:
                tracks_to_keep.append(track)
                print("    → Will be kept (operation will be cancelled)")
            print()
    
    finally:
        session.close()
    
    if tracks_to_keep:
        print(f"⚠ {len(tracks_to_keep)} tracks will not be skipped.")
        print("Operation cancelled. Please add these tracks to your library and try again.")
        return None  # Signal to cancel
    
    return tracks_to_skip


# ----------------------------
# Stage functions
# ----------------------------

def _scrape_and_prompt_name(url: str, artifacts_dir: Path, prompt_for_name: bool = True) -> tuple[dict, Path]:
    """
    Helper function to scrape a playlist and optionally prompt for a custom name.
    
    Args:
        url: Playlist URL to scrape
        artifacts_dir: Directory to save artifacts
        prompt_for_name: Whether to prompt the user for a custom name
    
    Returns:
        Tuple of (playlist_data, output_path)
    """
    print_title("STAGE 1: SCRAPING PLAYLIST")
    print(f"Scraping: {url}")
    print("Please wait...")
    print()
    
    playlist_data = playlist_scraper(url)
    track_count = playlist_data.get("meta", {}).get("track_count", 0)
    playlist_title = playlist_data.get("meta", {}).get("playlist_title", "Unknown")
    
    # Generate default name
    default_stem = derive_artifact_stem(playlist_data.get("meta", {}))
    # Extract just the name part (without date prefix) for the prompt default
    default_name = default_stem.split('_', 1)[1] if '_' in default_stem else default_stem
    # Full filename that will be used
    default_filename = f"{default_stem}.playlist.json"
    
    print(f"✓ Successfully scraped playlist: {playlist_title}")
    print(f"✓ Found {track_count} tracks")
    print()
    
    # Prompt for custom name if requested
    custom_name = None
    if prompt_for_name:
        print("Enter a custom name for this playlist artifact.")
        print(f"Auto-generated name: {default_filename}")
        print("(Enter a custom name, or press Enter to use the auto-generated name)")
        print()
        custom_name_input = prompt_user("Playlist name", default_name).strip()
        if custom_name_input and custom_name_input != default_name:
            custom_name = custom_name_input
    
    # Derive artifact filename with custom name (or use default)
    stem = derive_artifact_stem(playlist_data.get("meta", {}), custom_name=custom_name)
    output_path = artifacts_dir / f"{stem}.playlist.json"
    
    # Save playlist JSON
    save_json(playlist_data, output_path)
    
    print(f"✓ Saved to: {output_path.resolve()}")
    print()
    
    return playlist_data, output_path


def run_scrape(url: str, artifacts_dir: Path, custom_name: str = None) -> Path:
    """
    Stage 1: Scrape playlist from URL and save to JSON artifact.
    
    Args:
        url: Playlist URL to scrape
        artifacts_dir: Directory to save artifacts
        custom_name: Optional custom name for the artifact (will be slugified)
    
    Returns:
        Path to saved playlist JSON file
    """
    print_title("STAGE 1: SCRAPING PLAYLIST")
    print(f"Scraping: {url}")
    print("Please wait...")
    
    try:
        playlist_data = playlist_scraper(url)
        track_count = playlist_data.get("meta", {}).get("track_count", 0)
        playlist_title = playlist_data.get("meta", {}).get("playlist_title", "Unknown")
        
        # Derive artifact filename
        stem = derive_artifact_stem(playlist_data.get("meta", {}), custom_name=custom_name)
        output_path = artifacts_dir / f"{stem}.playlist.json"
        
        # Save playlist JSON
        save_json(playlist_data, output_path)
        
        print(f"✓ Successfully scraped playlist: {playlist_title}")
        print(f"✓ Found {track_count} tracks")
        print(f"✓ Saved to: {output_path.resolve()}")
        print()
        
        return output_path
        
    except Exception as e:
        print(f"Error scraping playlist: {e}")
        raise


def run_match(playlist_json_path: Path, base_folder: str, library_subpath: str, artifacts_dir: Path) -> Path:
    """
    Stage 2: Match playlist tracks to library and save match report.
    
    Args:
        playlist_json_path: Path to playlist JSON file
        base_folder: Base folder containing library
        library_subpath: Subpath to library within base_folder
        artifacts_dir: Directory to save artifacts
    
    Returns:
        Path to saved match JSON file
    """
    print_title("STAGE 2: MATCHING TRACKS TO LIBRARY")
    
    # Load playlist data
    playlist_data = load_json(playlist_json_path)
    
    # Print track list
    tracks = playlist_data.get("tracks", [])
    if tracks:
        print_track_list(tracks, f"PLAYLIST TRACKS ({len(tracks)} tracks)")
    
    print("Matching tracks to library...")
    print("Please wait...")
    
    try:
        match_result = match_playlist_to_library(
            data=playlist_data,
            base_folder=base_folder,
            library_subpath=library_subpath,
            include_candidates=True,
            max_candidates=5,
        )
        
        # Include original playlist data in match report for Stage 4
        match_result["playlist_data"] = playlist_data
        
        found = match_result["summary"]["found"]
        missing = match_result["summary"]["missing"]
        total = match_result["summary"]["total_tracks"]
        
        # Extract stem from playlist JSON filename to maintain consistent naming
        stem = extract_stem_from_playlist_path(playlist_json_path)
        output_path = artifacts_dir / f"{stem}.match.json"
        
        # Save match report
        save_json(match_result, output_path)
        
        print(f"✓ Matched {found} of {total} tracks")
        if missing > 0:
            print(f"⚠ {missing} tracks not found in library")
            print()
            
            # Display missing tracks with artist, album, and track info
            missing_tracks = [r for r in match_result["results"] if r["match_status"] == "missing"]
            if missing_tracks:
                print_title(f"MISSING TRACKS ({len(missing_tracks)} of {total})")
                for i, track in enumerate(missing_tracks, 1):
                    artist = track.get('artist', 'Unknown Artist')
                    song = track.get('song', 'Unknown Song')
                    album = track.get('album', '')
                    
                    print(f"  {i:3d}. {artist} - {song}")
                    if album:
                        print(f"       Album: {album}")
                print()
        else:
            print("✓ All tracks found in library!")
        print(f"✓ Saved to: {output_path.resolve()}")
        print()
        
        return output_path
        
    except Exception as e:
        print(f"Error matching tracks: {e}")
        raise


def prompt_streaming_service(skip_if_set: bool = True) -> str:
    """
    Get streaming service from settings if valid, otherwise prompt user.
    
    Args:
        skip_if_set: If True and valid setting exists, return it without prompting
    
    Returns:
        Selected service key: "amazon_music" or "tidal"
    """
    # Get saved preference
    saved_service = get_setting("streaming_service", "amazon_music")
    
    # Validate setting
    if saved_service in ("amazon_music", "tidal"):
        if skip_if_set:
            # Valid setting exists, use it silently
            return saved_service
    
    # Invalid setting or skip_if_set is False, prompt user
    default_choice = "1" if saved_service == "amazon_music" else "2"
    
    print_title("SELECT STREAMING SERVICE")
    print("Choose which streaming service links you want to receive:")
    print("1. Amazon Music")
    print("2. Tidal")
    print()
    
    while True:
        choice = prompt_user("Select service (1 or 2)", default_choice).strip()
        if choice == "1":
            selected = "amazon_music"
            # Save preference
            if selected != saved_service:
                set_setting("streaming_service", selected)
            return selected
        elif choice == "2":
            selected = "tidal"
            # Save preference
            if selected != saved_service:
                set_setting("streaming_service", selected)
            return selected
        else:
            print("Invalid choice. Please enter 1 for Amazon Music or 2 for Tidal.")
            print()


def run_links(match_json_path: Path, artifacts_dir: Path, missing_only: bool = True) -> Path:
    """
    Stage 3: Enrich missing tracks with streaming links.
    
    Args:
        match_json_path: Path to match JSON file
        artifacts_dir: Directory to save artifacts
        missing_only: If True, only enrich missing tracks; if False, enrich all tracks
    
    Returns:
        Path to saved enriched JSON file
    """
    print_title("STAGE 3: ENRICHING TRACKS WITH STREAMING LINKS")
    
    # Get streaming service (skip prompt if valid setting exists)
    selected_service = prompt_streaming_service(skip_if_set=True)
    service_display_name = "Amazon Music" if selected_service == "amazon_music" else "Tidal"
    print(f"✓ Using streaming service: {service_display_name}")
    print()
    
    # Load match result
    match_result = load_json(match_json_path)
    
    # Determine which tracks to enrich
    if missing_only:
        tracks_to_enrich = [r for r in match_result["results"] if r["match_status"] == "missing"]
    else:
        tracks_to_enrich = match_result["results"]
    
    if not tracks_to_enrich:
        print("ℹ No tracks to enrich.")
        print()
        return match_json_path
    
    # Get total tracks count from match result
    total_tracks = match_result.get("summary", {}).get("total_tracks", len(tracks_to_enrich))
    
    # Print title with count (without listing individual tracks)
    enrich_type = "MISSING TRACKS" if missing_only else "ALL TRACKS"
    print_title(f"{enrich_type} TO ENRICH ({len(tracks_to_enrich)} tracks/{total_tracks})")
    
    print(f"Enriching {len(tracks_to_enrich)} track(s) with {service_display_name} links...")
    print()
    
    session = requests.Session()
    links_found = 0
    tracks_without_links = []
    
    try:
        # Use tqdm to show progress bar
        for track in tqdm(tracks_to_enrich, desc="Enriching tracks", unit="track"):
            try:
                track_meta = TrackMeta(
                    artist=track.get('artist', ''),
                    title=track.get('song', ''),
                    album=track.get('album')
                )
                link_result = find_share_urls_from_metadata(
                    track_meta,
                    session=session,
                    use_cache=True
                )
                
                # Attach link result to track, filtered by selected service
                if link_result.get("ok"):
                    all_targets = link_result.get("aggregated", {}).get("targets", {})
                    
                    # Filter to only include the selected service
                    filtered_targets = {}
                    if selected_service in all_targets and all_targets[selected_service]:
                        filtered_targets[selected_service] = all_targets[selected_service]
                    
                    track["share_links"] = filtered_targets
                    track["songlink_page"] = link_result.get("aggregated", {}).get("page_url")
                    track["link_seed"] = link_result.get("seed")
                    
                    # Store album links if available (only Amazon Music currently supports this)
                    album_aggregated = link_result.get("album_aggregated", {})
                    if album_aggregated:
                        album_targets = album_aggregated.get("targets", {})
                        # Filter to only include the selected service
                        filtered_album_targets = {}
                        if selected_service in album_targets and album_targets[selected_service]:
                            filtered_album_targets[selected_service] = album_targets[selected_service]
                        track["album_share_links"] = filtered_album_targets
                    else:
                        track["album_share_links"] = {}
                    
                    if filtered_targets:
                        links_found += 1
                    else:
                        # Track link lookup succeeded but no links found for selected service
                        tracks_without_links.append(track)
                else:
                    track["share_links"] = {}
                    track["album_share_links"] = {}
                    track["songlink_page"] = None
                    track["link_seed"] = None
                    # Track link lookup failed
                    tracks_without_links.append(track)
            except Exception:
                # Silently handle errors
                track["share_links"] = {}
                track["album_share_links"] = {}
                track["songlink_page"] = None
                track["link_seed"] = None
                # Track error during link lookup
                tracks_without_links.append(track)
        
        # Extract stem from match JSON filename to maintain consistent naming
        # The match file stem should match the playlist file stem
        stem = extract_stem_from_artifact_path(match_json_path)
        output_path = artifacts_dir / f"{stem}.enriched.json"
        
        # Save enriched match report
        save_json(match_result, output_path)
        
        print()
        print(f"✓ Found links for {links_found} of {len(tracks_to_enrich)} track(s)")
        print(f"✓ Saved to: {output_path.resolve()}")
        print()
        
        # Print enriched track list with links
        enrich_type = "ENRICHED MISSING TRACKS" if missing_only else "ENRICHED TRACKS"
        print_track_list_with_links(tracks_to_enrich, f"{enrich_type} ({len(tracks_to_enrich)} tracks)")
        
        # Print album links summary
        print_album_links_summary(tracks_to_enrich)
        
        # Print tracks where links could not be found
        if tracks_without_links:
            print_title(f"TRACKS WITHOUT LINKS ({len(tracks_without_links)} tracks)")
            for track in tracks_without_links:
                artist = track.get('artist', 'Unknown Artist')
                album = track.get('album', '')
                # Use album if available, otherwise use song title
                if album:
                    print(f"  {artist} - {album}")
                else:
                    song = track.get('song', 'Unknown Song')
                    print(f"  {artist} - {song}")
            print()
        
        return output_path
        
    finally:
        session.close()


def run_export(input_path: Path, base_folder: str, library_subpath: str, target_dir: Path, overwrite: bool = False) -> Path:
    """
    Stage 4: Export playlist folder from match report or playlist JSON.
    
    Args:
        input_path: Path to match JSON or playlist JSON file
        base_folder: Base folder containing library
        library_subpath: Subpath to library within base_folder
        target_dir: Directory where playlist folder should be created
        overwrite: Whether to overwrite existing files
    
    Returns:
        Path to created playlist folder
    """
    print_title("STAGE 4: EXPORTING PLAYLIST FOLDER")
    
    # Load input data
    input_data = load_json(input_path)
    
    # Determine if input is a match report or playlist JSON
    if "playlist_data" in input_data:
        # It's a match report - use embedded playlist data
        playlist_data = input_data["playlist_data"]
        match_result = input_data
        
        # Check for missing tracks and optionally skip them
        still_missing = [r for r in match_result["results"] if r["match_status"] == "missing"]
        if still_missing:
            print(f"⚠ {len(still_missing)} tracks are still missing in library.")
            if prompt_yes_no("Skip missing tracks and export anyway?", default=False):
                # Filter out missing tracks
                skipped_artists_songs = {(t['artist'], t['song']) for t in still_missing}
                original_tracks = playlist_data.get('tracks', [])
                filtered_tracks = [
                    t for t in original_tracks
                    if (t.get('artist', ''), t.get('song', '')) not in skipped_artists_songs
                ]
                playlist_data['tracks'] = filtered_tracks
                playlist_data['meta']['track_count'] = len(filtered_tracks)
                print(f"ℹ {len(still_missing)} tracks will be skipped.")
            else:
                print("Export cancelled.")
                raise SystemExit(0)
    else:
        # It's a playlist JSON - use it directly
        playlist_data = input_data
    
    print("Creating playlist...")
    print("Please wait...")
    
    try:
        result = export_playlist_copies(
            data=playlist_data,
            base_folder=base_folder,
            target_dir=str(target_dir),
            library_subpath=library_subpath,
            make_subfolder=True,
            overwrite=overwrite,
        )
        
        copied = result["summary"]["copied"]
        total = result["summary"]["total_tracks"]
        dest_folder = Path(result["destination_folder"])
        
        print(f"✓ Playlist created successfully!")
        print(f"✓ Location: {dest_folder}")
        print(f"✓ Tracks copied: {copied} of {total}")
        print(f"✓ Manifest: {dest_folder / 'manifest.json'}")
        print()
        
        return dest_folder
        
    except Exception as e:
        print(f"Error creating playlist: {e}")
        raise


def run_guided_pipeline(base_folder: str, library_subpath: str, artifacts_dir: Path) -> None:
    """
    Run the full guided pipeline (preserves original behavior).
    
    This runs stages 1-4 end-to-end with user interaction for missing tracks.
    """
    print_title("GUIDED PIPELINE")
    print("This will run the full workflow with guided interaction.")
    print()
    
    # Step 1: Get playlist URL
    print_title("STEP 1: PLAYLIST URL")
    url = prompt_user("Enter playlist URL")
    if not url:
        print("Error: URL is required.")
        sys.exit(1)
    
    # Stage 1: Scrape (with optional custom name)
    try:
        playlist_data, playlist_json_path = _scrape_and_prompt_name(url, artifacts_dir, prompt_for_name=True)
    except Exception as e:
        print(f"Error scraping playlist: {e}")
        raise
    
    # Stage 2: Match
    match_json_path = run_match(playlist_json_path, base_folder, library_subpath, artifacts_dir)
    match_result = load_json(match_json_path)
    
    # Step 3: Handle missing tracks (interactive)
    missing_tracks = display_missing_tracks(match_result)
    
    if missing_tracks:
        print_title("MISSING TRACKS DETECTED")
        
        # Calculate library root path
        library_root_path = Path(base_folder)
        if library_subpath:
            library_root_path = library_root_path / library_subpath
        library_root_path = library_root_path.resolve()
        
        # Offer to create artist directories
        create_artist_directories(missing_tracks, library_root_path)
        
        print("Please add the missing tracks to your library, then confirm when ready.")
        print()
        
        if not prompt_yes_no("Have you added all missing tracks to the library?", default=False):
            print("Exiting. Please add the tracks and run again.")
            sys.exit(0)
        
        # Re-match after user confirms
        print()
        print("Re-matching tracks...")
        match_result = match_playlist_to_library(
            data=playlist_data,
            base_folder=base_folder,
            library_subpath=library_subpath,
            include_candidates=True,
            max_candidates=5,
        )
        
        # Update match report with new results and playlist data
        match_result["playlist_data"] = playlist_data
        save_json(match_result, match_json_path)
        
        still_missing = [r for r in match_result["results"] if r["match_status"] == "missing"]
        if still_missing:
            # Ask user to confirm skipping each track
            confirmed_skips = confirm_skip_tracks(still_missing)
            
            if confirmed_skips is None:
                # User chose not to skip some tracks
                print("Exiting.")
                sys.exit(0)
            
            if len(confirmed_skips) < len(still_missing):
                # Some tracks were not confirmed to skip - this shouldn't happen but handle it
                print("Warning: Not all tracks were confirmed to skip.")
                if not prompt_yes_no("Continue with confirmed skips only?", default=False):
                    print("Exiting.")
                    sys.exit(0)
            
            # Remove skipped tracks from playlist_data for playlist creation
            skipped_artists_songs = {(t['artist'], t['song']) for t in confirmed_skips}
            original_tracks = playlist_data.get('tracks', [])
            filtered_tracks = [
                t for t in original_tracks
                if (t.get('artist', ''), t.get('song', '')) not in skipped_artists_songs
            ]
            playlist_data['tracks'] = filtered_tracks
            playlist_data['meta']['track_count'] = len(filtered_tracks)
            
            # Update saved playlist JSON
            save_json(playlist_data, playlist_json_path)
            
            # Re-run match to update match report
            match_result = match_playlist_to_library(
                data=playlist_data,
                base_folder=base_folder,
                library_subpath=library_subpath,
                include_candidates=True,
                max_candidates=5,
            )
            match_result["playlist_data"] = playlist_data
            save_json(match_result, match_json_path)
            
            print(f"ℹ {len(confirmed_skips)} tracks will be skipped in playlist creation.")
            print()
    
    # Step 4: Get target location and export
    default_target = get_setting("export.default_target_dir", "")
    
    # Check if target directory is valid
    target_path = None
    if default_target:
        target_path = Path(default_target).expanduser()
        if not target_path.exists():
            target_path = None
    
    if target_path:
        # Valid setting exists, use it silently
        print_title("STEP 4: CREATE PLAYLIST")
        print(f"Using saved target directory: {target_path}")
        print()
    else:
        # Settings invalid or missing, prompt user
        print_title("STEP 4: CREATE PLAYLIST")
        print("Enter the target location where the playlist folder should be created.")
        print("Example: ~/Desktop or /Users/username/Desktop")
        print()
        
        target_dir = prompt_user("Target directory", default_target)
        if not target_dir:
            print("Error: Target directory is required.")
            sys.exit(1)
        
        target_path = Path(target_dir).expanduser()
        if not target_path.exists():
            print(f"Error: Target directory does not exist: {target_path}")
            sys.exit(1)
        
        # Save to settings
        set_setting("export.default_target_dir", target_dir)
    
    # Stage 4: Export (use match report)
    run_export(match_json_path, base_folder, library_subpath, target_path, overwrite=False)
    
    print("✓ Pipeline completed successfully!")


def validate_url(url: str) -> str:
    """
    Validate that a string looks like a URL.
    
    Args:
        url: URL string to validate
    
    Returns:
        Validated URL string
    
    Raises:
        ValueError: If URL doesn't look valid
    """
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty")
    
    # Basic URL validation - must start with http:// or https://
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"URL must start with http:// or https://: {url}")
    
    return url


def validate_file_path(path: Path, file_type: str = "file") -> Path:
    """
    Validate that a file path exists and return the resolved path.
    
    Args:
        path: Path to validate
        file_type: Type description for error messages (e.g., "file", "directory")
    
    Returns:
        Resolved Path object
    
    Raises:
        FileNotFoundError: If path doesn't exist
    """
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"{file_type.capitalize()} not found: {resolved}")
    return resolved


def validate_json_file(path: Path, expected_type: str = None) -> dict:
    """
    Validate and load a JSON file, optionally checking its structure.
    
    Args:
        path: Path to JSON file
        expected_type: Optional expected type hint ("playlist", "match", etc.)
    
    Returns:
        Parsed JSON dict
    
    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
        ValueError: If file doesn't match expected type
    """
    resolved = validate_file_path(path, "JSON file")
    
    try:
        data = load_json(resolved)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON file: {resolved}\nError: {e}")
    
    # Basic type validation
    if expected_type == "playlist":
        if "meta" not in data or "tracks" not in data:
            raise ValueError(f"File does not appear to be a playlist JSON: {resolved}\n"
                           f"Expected keys: 'meta', 'tracks'")
    elif expected_type == "match":
        if "summary" not in data or "results" not in data:
            raise ValueError(f"File does not appear to be a match JSON: {resolved}\n"
                           f"Expected keys: 'summary', 'results'")
    
    return data


def list_artifacts(artifact_type: str = None) -> list[Path]:
    """
    List available artifact files in the artifacts directory.
    
    Args:
        artifact_type: Optional filter by type ("playlist", "match", "enriched")
    
    Returns:
        List of Path objects to artifact files
    """
    if not ARTIFACTS_DIR.exists():
        return []
    
    artifacts = []
    pattern = f"*.{artifact_type}.json" if artifact_type else "*.json"
    
    for path in sorted(ARTIFACTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file():
            artifacts.append(path)
    
    return artifacts


def group_artifacts_by_stem() -> dict[str, list[Path]]:
    """
    Group artifact files by their stem (the part before the type suffix).
    
    Returns:
        Dict mapping stem to list of Path objects for that stem
        Example: {"2025-12-19_playlist-name": [playlist.json, match.json, enriched.json]}
    """
    if not ARTIFACTS_DIR.exists():
        return {}
    
    grouped = {}
    
    for path in ARTIFACTS_DIR.glob("*.json"):
        if not path.is_file():
            continue
        
        # Extract stem from filename like "2025-12-19_name.playlist.json"
        # or "2025-12-19_name.match.json"
        stem = path.stem  # Gets "2025-12-19_name.playlist" or "2025-12-19_name.match"
        
        # Remove the type suffix (.playlist, .match, .enriched)
        if stem.endswith(".playlist"):
            stem = stem[:-9]  # Remove ".playlist"
        elif stem.endswith(".match"):
            stem = stem[:-6]  # Remove ".match"
        elif stem.endswith(".enriched"):
            stem = stem[:-9]  # Remove ".enriched"
        
        if stem not in grouped:
            grouped[stem] = []
        grouped[stem].append(path)
    
    # Sort files within each group by modification time (newest first)
    for stem in grouped:
        grouped[stem].sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    return grouped


def prompt_file_path(prompt_text: str, file_type: str = "file", must_exist: bool = True, 
                     expected_json_type: str = None, show_artifacts: bool = False) -> Path:
    """
    Prompt user for a file path with validation.
    
    Args:
        prompt_text: Prompt message
        file_type: Type description for error messages
        must_exist: Whether file must exist
        expected_json_type: If provided, validate JSON structure ("playlist", "match")
        show_artifacts: If True, show available artifacts before prompting
    
    Returns:
        Validated Path object
    """
    # Show available artifacts if requested
    if show_artifacts:
        artifacts = list_artifacts(expected_json_type)
        if artifacts:
            print()
            print(f"Available {expected_json_type or 'artifact'} files in {ARTIFACTS_DIR.resolve()}:")
            for i, artifact in enumerate(artifacts[:10], 1):  # Show up to 10 most recent
                # Show modification time to help identify recently created files
                try:
                    mtime = artifact.stat().st_mtime
                    time_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                    
                    # For match files, try to show playlist title for easier identification
                    extra_info = ""
                    if expected_json_type == "match":
                        try:
                            data = load_json(artifact)
                            playlist_data = data.get("playlist_data", {})
                            if playlist_data:
                                playlist_title = playlist_data.get("meta", {}).get("playlist_title", "")
                                if playlist_title:
                                    extra_info = f" | Playlist: {playlist_title}"
                        except Exception:
                            pass  # Silently ignore errors loading JSON
                    
                    print(f"  {i}. {artifact.name} (modified: {time_str}{extra_info})")
                except Exception:
                    print(f"  {i}. {artifact.name}")
            if len(artifacts) > 10:
                print(f"  ... and {len(artifacts) - 10} more")
            print()
            max_num = min(10, len(artifacts))
            choice_str = prompt_user(f"Enter number (1-{max_num}) to select, 'n' for custom path, or enter path directly", "").strip()
            
            if choice_str:
                # Check if it's 'n' for custom path - fall through to path input below
                if choice_str.lower() == 'n':
                    # Fall through to path input loop below
                    pass
                else:
                    # Try to parse as number
                    try:
                        choice_num = int(choice_str)
                        if 1 <= choice_num <= max_num:
                            return artifacts[choice_num - 1].resolve()
                        else:
                            print(f"Error: Please enter a number between 1 and {max_num}")
                            print()
                            # Fall through to path input loop
                    except ValueError:
                        # Treat as path directly
                        try:
                            path = Path(choice_str).expanduser()
                            
                            # If path is relative and artifacts dir exists, check there first
                            if not path.is_absolute() and ARTIFACTS_DIR.exists():
                                artifact_path = ARTIFACTS_DIR / choice_str
                                if artifact_path.exists():
                                    path = artifact_path
                            
                            if must_exist:
                                if expected_json_type:
                                    validate_json_file(path, expected_json_type)
                                else:
                                    validate_file_path(path, file_type)
                            
                            return path.resolve()
                        except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
                            print(f"Error: {e}")
                            print()
                            # Fall through to path input loop
            else:
                # Empty input - fall through to path input loop
                pass
    
    while True:
        path_str = prompt_user(prompt_text)
        if not path_str:
            print(f"Error: {file_type.capitalize()} path is required.")
            if not prompt_yes_no("Try again?", default=True):
                print("Goodbye!")
                raise SystemExit(0)
            continue
        
        try:
            path = Path(path_str).expanduser()
            
            # If path is relative and artifacts dir exists, check there first
            if not path.is_absolute() and ARTIFACTS_DIR.exists():
                artifact_path = ARTIFACTS_DIR / path_str
                if artifact_path.exists():
                    path = artifact_path
            
            if must_exist:
                if expected_json_type:
                    # Validate JSON structure
                    validate_json_file(path, expected_json_type)
                else:
                    validate_file_path(path, file_type)
            
            return path.resolve()
            
        except FileNotFoundError as e:
            print(f"Error: {e}")
            if ARTIFACTS_DIR.exists() and not path.is_absolute():
                artifacts = list_artifacts(expected_json_type)
                if artifacts:
                    print(f"\nTip: Available {expected_json_type or 'artifact'} files:")
                    for artifact in artifacts[:5]:
                        print(f"  - {artifact.name}")
            if prompt_yes_no("Try again?", default=True):
                continue
            print("Goodbye!")
            raise SystemExit(0)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"Error: {e}")
            if prompt_yes_no("Try again?", default=True):
                continue
            print("Goodbye!")
            raise SystemExit(0)


# ----------------------------
# Menu system
# ----------------------------

def display_main_menu() -> None:
    """Display the main menu options."""
    print_title("MAIN MENU")
    print("1. Scrape playlist (save JSON artifact)")
    print("2. Match playlist JSON to library (save match report)")
    print("3. Enrich missing tracks with streaming links (save enriched report)")
    print("4. Export playlist folder (from match report or playlist JSON)")
    print("5. Catalog new music into library")
    print("6. Run full pipeline (guided)")
    print("7. Clean up old playlist artifacts")
    print("8. Configure settings")
    print("9. Quit")
    print()


def handle_operation_error(error: Exception, operation_name: str = "Operation") -> bool:
    """
    Handle errors from menu operations with consistent user interaction.
    
    Args:
        error: The exception that occurred
        operation_name: Name of the operation for error messages
    
    Returns:
        True if user wants to return to menu, False if they want to quit
    """
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        print("\nOperation cancelled.")
    else:
        print(f"\nError: {error}")
    
    return prompt_yes_no("Return to main menu?", default=True)


def handle_scrape_option() -> bool:
    """
    Handle menu option 1: Scrape playlist.
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    try:
        while True:
            url = prompt_user("Enter playlist URL")
            if not url:
                print("Error: URL is required.")
                if not prompt_yes_no("Try again?", default=True):
                    break
                continue
            
            try:
                url = validate_url(url)
                break
            except ValueError as e:
                print(f"Error: {e}")
                if not prompt_yes_no("Try again?", default=True):
                    break
        
        if not url:
            return prompt_yes_no("Return to main menu?", default=True)
        
        try:
            _, output_path = _scrape_and_prompt_name(url, ARTIFACTS_DIR, prompt_for_name=True)
            print("\n✓ Stage 1 completed successfully!")
            return True
        except Exception as e:
            print(f"Error scraping playlist: {e}")
            raise
        
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        return prompt_yes_no("Return to main menu?", default=True)
    except Exception as e:
        return handle_operation_error(e, "Scrape")


def handle_match_option() -> bool:
    """
    Handle menu option 2: Match playlist to library.
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    try:
        playlist_path = prompt_file_path(
            "Enter path to playlist JSON file",
            file_type="playlist JSON file",
            expected_json_type="playlist",
            show_artifacts=True
        )
        base_folder, library_subpath = get_library_path()
        run_match(playlist_path, base_folder, library_subpath, ARTIFACTS_DIR)
        print("\n✓ Stage 2 completed successfully!")
        return True
        
    except (KeyboardInterrupt, SystemExit):
        return handle_operation_error(SystemExit(), "Match")
    except Exception as e:
        return handle_operation_error(e, "Match")


def handle_enrich_option() -> bool:
    """
    Handle menu option 3: Enrich tracks with streaming links.
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    try:
        match_path = prompt_file_path(
            "Enter path to match JSON file",
            file_type="match JSON file",
            expected_json_type="match",
            show_artifacts=True
        )
        missing_only = prompt_yes_no("Enrich only missing tracks?", default=True)
        run_links(match_path, ARTIFACTS_DIR, missing_only=missing_only)
        print("\n✓ Stage 3 completed successfully!")
        return True
        
    except (KeyboardInterrupt, SystemExit):
        return handle_operation_error(SystemExit(), "Enrich")
    except Exception as e:
        return handle_operation_error(e, "Enrich")


def handle_export_option() -> bool:
    """
    Handle menu option 4: Export playlist folder.
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    try:
        input_path = prompt_file_path(
            "Enter path to match JSON or playlist JSON file",
            file_type="JSON file",
            show_artifacts=True
        )
        
        # Try to determine type for better error messages
        try:
            data = load_json(input_path)
            if "playlist_data" in data or ("summary" in data and "results" in data):
                # It's a match JSON
                pass
            elif "meta" in data and "tracks" in data:
                # It's a playlist JSON
                pass
            else:
                print("Warning: File structure unclear. Proceeding anyway...")
        except Exception:
            pass  # Will be caught by run_export if it's invalid
        
        base_folder, library_subpath = get_library_path()
        
        default_target = get_setting("export.default_target_dir", "")
        
        # Check if target directory is valid
        target_dir = None
        if default_target:
            try:
                target_dir = validate_file_path(Path(default_target).expanduser(), "directory")
            except FileNotFoundError:
                target_dir = None
        
        if target_dir:
            # Valid setting exists, use it silently
            print(f"Using saved target directory: {target_dir}")
            print()
        else:
            # Settings invalid or missing, prompt user
            target_dir_str = prompt_user("Enter target directory for playlist folder", default_target)
            if not target_dir_str:
                print("Error: Target directory is required.")
                return prompt_yes_no("Return to main menu?", default=True)
            
            try:
                target_dir = validate_file_path(Path(target_dir_str).expanduser(), "directory")
            except FileNotFoundError as e:
                print(f"Error: {e}")
                return prompt_yes_no("Return to main menu?", default=True)
            
            # Save to settings
            set_setting("export.default_target_dir", target_dir_str)
        
        overwrite = prompt_yes_no("Overwrite existing files?", default=False)
        run_export(input_path, base_folder, library_subpath, target_dir, overwrite=overwrite)
        print("\n✓ Stage 4 completed successfully!")
        return True
        
    except (KeyboardInterrupt, SystemExit):
        return handle_operation_error(SystemExit(), "Export")
    except Exception as e:
        return handle_operation_error(e, "Export")


def handle_catalog_option() -> bool:
    """
    Handle menu option 5: Catalog new music.
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    try:
        base_folder, library_subpath = get_library_path()
        catalog_new_music(base_folder, library_subpath)
        return True
        
    except (KeyboardInterrupt, SystemExit):
        return handle_operation_error(SystemExit(), "Catalog")
    except Exception as e:
        return handle_operation_error(e, "Catalog")


def handle_guided_pipeline_option() -> bool:
    """
    Handle menu option 6: Run guided pipeline.
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    try:
        base_folder, library_subpath = get_library_path()
        run_guided_pipeline(base_folder, library_subpath, ARTIFACTS_DIR)
        return True
        
    except (KeyboardInterrupt, SystemExit):
        return handle_operation_error(SystemExit(), "Guided Pipeline")
    except Exception as e:
        return handle_operation_error(e, "Guided Pipeline")


def handle_cleanup_option() -> bool:
    """
    Handle menu option 7: Clean up old playlist artifacts.
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    try:
        print_title("CLEAN UP ARTIFACTS")
        
        # Group artifacts by stem
        grouped = group_artifacts_by_stem()
        
        if not grouped:
            print("No artifacts found to clean up.")
            print()
            return True
        
        # Sort stems by date (newest first)
        stems = sorted(grouped.keys(), key=lambda s: s.split('_')[0] if '_' in s else '', reverse=True)
        
        print(f"Found {len(stems)} playlist artifact group(s):")
        print()
        
        # Display grouped artifacts
        for i, stem in enumerate(stems, 1):
            files = grouped[stem]
            file_types = [f.stem.split('.')[-1] if '.' in f.stem else 'unknown' for f in files]
            file_types_str = ', '.join(sorted(set(file_types)))
            
            # Get the most recent modification time
            most_recent = max(f.stat().st_mtime for f in files)
            date_str = datetime.fromtimestamp(most_recent).strftime("%Y-%m-%d %H:%M")
            
            print(f"  {i}. {stem}")
            print(f"     Files: {file_types_str} ({len(files)} file(s))")
            print(f"     Last modified: {date_str}")
            print()
        
        # Prompt for selection
        print("Enter the numbers of the artifact groups to delete (comma-separated),")
        print("or 'all' to delete everything, or press Enter to cancel.")
        print()
        selection = prompt_user("Selection", "").strip()
        
        if not selection:
            print("Cleanup cancelled.")
            print()
            return True
        
        # Parse selection
        stems_to_delete = []
        if selection.lower() == 'all':
            stems_to_delete = stems
        else:
            try:
                indices = [int(x.strip()) for x in selection.split(',')]
                for idx in indices:
                    if 1 <= idx <= len(stems):
                        stems_to_delete.append(stems[idx - 1])
                    else:
                        print(f"Warning: Invalid number {idx}, skipping.")
            except ValueError:
                print("Error: Invalid selection format. Please enter numbers separated by commas.")
                return prompt_yes_no("Return to main menu?", default=True)
        
        if not stems_to_delete:
            print("No artifacts selected for deletion.")
            print()
            return True
        
        # Confirm deletion
        total_files = sum(len(grouped[stem]) for stem in stems_to_delete)
        print()
        print(f"You are about to delete {len(stems_to_delete)} artifact group(s) ({total_files} file(s) total):")
        for stem in stems_to_delete:
            print(f"  - {stem} ({len(grouped[stem])} file(s))")
        print()
        
        if not prompt_yes_no("Are you sure you want to delete these artifacts?", default=False):
            print("Deletion cancelled.")
            print()
            return True
        
        # Delete the files
        deleted_count = 0
        failed_count = 0
        
        for stem in stems_to_delete:
            for file_path in grouped[stem]:
                try:
                    file_path.unlink()
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {file_path.name}: {e}")
                    failed_count += 1
        
        print()
        print_separator()
        print(f"✓ Deleted {deleted_count} file(s)")
        if failed_count > 0:
            print(f"⚠ Failed to delete {failed_count} file(s)")
        print()
        
        return True
        
    except (KeyboardInterrupt, SystemExit):
        return handle_operation_error(SystemExit(), "Cleanup")
    except Exception as e:
        return handle_operation_error(e, "Cleanup")


def handle_settings_option() -> bool:
    """
    Handle menu option 8: Configure settings.
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    try:
        print_title("CONFIGURE SETTINGS")
        settings = load_settings()
        
        while True:
            print("Current settings:")
            print()
            print(f"1. Library base folder: {settings['library']['base_folder']}")
            print(f"2. Library subpath: {settings['library']['library_subpath'] or '(none)'}")
            print(f"3. Streaming service: {settings['streaming_service'].replace('_', ' ').title()}")
            print(f"4. Catalog drop location: {settings['catalog']['drop_location'] or '(not set)'}")
            print(f"5. Catalog move files: {settings['catalog']['move_files']}")
            print(f"6. Catalog skip duplicates: {settings['catalog']['skip_duplicates']}")
            print(f"7. Export default target directory: {settings['export']['default_target_dir'] or '(not set)'}")
            print("8. Return to main menu")
            print()
            
            choice = prompt_user("Select setting to change (1-8)", "8").strip()
            
            if choice == "8":
                break
            elif choice == "1":
                new_value = prompt_user("Enter library base folder", settings['library']['base_folder'])
                if new_value:
                    settings['library']['base_folder'] = new_value
                    save_settings(settings)
                    print("✓ Setting saved.")
            elif choice == "2":
                new_value = prompt_user("Enter library subpath (press Enter for none)", settings['library']['library_subpath'])
                settings['library']['library_subpath'] = new_value
                save_settings(settings)
                print("✓ Setting saved.")
            elif choice == "3":
                print("1. Amazon Music")
                print("2. Tidal")
                service_choice = prompt_user("Select service (1 or 2)", "1" if settings['streaming_service'] == "amazon_music" else "2").strip()
                if service_choice == "1":
                    settings['streaming_service'] = "amazon_music"
                elif service_choice == "2":
                    settings['streaming_service'] = "tidal"
                else:
                    print("Invalid choice.")
                    continue
                save_settings(settings)
                print("✓ Setting saved.")
            elif choice == "4":
                new_value = prompt_user("Enter catalog drop location", settings['catalog']['drop_location'])
                settings['catalog']['drop_location'] = new_value
                save_settings(settings)
                print("✓ Setting saved.")
            elif choice == "5":
                new_value = prompt_yes_no("Move files to library? (No = copy files)", settings['catalog']['move_files'])
                settings['catalog']['move_files'] = new_value
                save_settings(settings)
                print("✓ Setting saved.")
            elif choice == "6":
                new_value = prompt_yes_no("Skip files that already exist in library?", settings['catalog']['skip_duplicates'])
                settings['catalog']['skip_duplicates'] = new_value
                save_settings(settings)
                print("✓ Setting saved.")
            elif choice == "7":
                new_value = prompt_user("Enter export default target directory", settings['export']['default_target_dir'])
                settings['export']['default_target_dir'] = new_value
                save_settings(settings)
                print("✓ Setting saved.")
            else:
                print("Invalid choice.")
            
            print()
        
        return True
        
    except (KeyboardInterrupt, SystemExit):
        return handle_operation_error(SystemExit(), "Settings")
    except Exception as e:
        return handle_operation_error(e, "Settings")


def handle_invalid_choice(choice: str) -> bool:
    """
    Handle invalid menu choice.
    
    Args:
        choice: The invalid choice string
    
    Returns:
        True if should continue menu loop, False if should exit
    """
    print()
    print(f"⚠ Invalid choice: '{choice}'")
    print("Please enter a number between 1 and 9.")
    print()
    return prompt_yes_no("Return to menu?", default=True)


def run_main_menu_loop() -> None:
    """
    Run the main menu loop until user quits.
    
    This function handles the menu display, choice routing, and loop control.
    """
    while True:
        display_main_menu()
        choice = prompt_user("Select option (1-9)", "1").strip()
        
        if choice == "9":
            print("Goodbye!")
            return
        
        should_continue = True
        
        if choice == "1":
            should_continue = handle_scrape_option()
        elif choice == "2":
            should_continue = handle_match_option()
        elif choice == "3":
            should_continue = handle_enrich_option()
        elif choice == "4":
            should_continue = handle_export_option()
        elif choice == "5":
            should_continue = handle_catalog_option()
        elif choice == "6":
            should_continue = handle_guided_pipeline_option()
        elif choice == "7":
            should_continue = handle_cleanup_option()
        elif choice == "8":
            should_continue = handle_settings_option()
        else:
            should_continue = handle_invalid_choice(choice)
        
        if not should_continue:
            print("Goodbye!")
            return


def main():
    """Main entry point."""
    print_banner()
    
    # Ensure artifacts directory exists
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    
    run_main_menu_loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
