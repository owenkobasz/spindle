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


def derive_artifact_stem(meta: dict) -> str:
    """
    Derive an artifact filename stem from playlist metadata.
    
    Args:
        meta: Playlist metadata dict
    
    Returns:
        Stem like "2025-12-17_lady-love"
    """
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
    Prompt user for library location with default of /Volumes/Music Library.
    
    Returns:
        Tuple of (base_folder, library_subpath)
    """
    print_title("LIBRARY LOCATION")
    print("Enter the path to your music library.")
    print("Press Enter to use the default, or enter a different path.")
    print()
    
    # Default library location
    default_base = "/Volumes/Music Library"
    
    base = prompt_user("Base folder", default_base)
    if not base:
        # If user cleared the default, use it anyway
        base = default_base
    
    # Check if base folder exists
    base_path = Path(base).expanduser()
    if not base_path.exists():
        print(f"Error: Base folder does not exist: {base_path}")
        sys.exit(1)
    
    # Ask for subpath if base might not be the library root
    subpath = prompt_user("Library subpath (press Enter if base folder IS the library)", "")
    
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
                    
                    # Album link
                    album_amazon = link_result.get('album_aggregated', {}).get('targets', {}).get('amazon_music') if link_result.get('album_aggregated') else None
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
    print_title("CATALOG NEW MUSIC")
    print("This will scan a drop location for music files and organize them")
    print("into your library structure (Artist/Album/Track).")
    print()
    
    # Get drop location
    drop_location = prompt_user("Enter drop location (where new music files are)")
    if not drop_location:
        print("Error: Drop location is required.")
        sys.exit(1)
    
    drop_path = Path(drop_location).expanduser()
    if not drop_path.exists():
        print(f"Error: Drop location does not exist: {drop_path}")
        sys.exit(1)
    
    # Calculate library root path
    library_root_path = Path(base_folder)
    if library_subpath:
        library_root_path = library_root_path / library_subpath
    library_root_path = library_root_path.resolve()
    
    if not library_root_path.exists():
        print(f"Error: Library root does not exist: {library_root_path}")
        sys.exit(1)
    
    print()
    print(f"Drop location: {drop_path}")
    print(f"Library root: {library_root_path}")
    print()
    
    # Ask about move vs copy
    move_files = prompt_yes_no("Move files to library? (No = copy files)", default=True)
    
    # Ask about duplicates
    skip_duplicates = prompt_yes_no("Skip files that already exist in library?", default=True)
    
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
                    
                    # Album link
                    album_amazon = link_result.get('album_aggregated', {}).get('targets', {}).get('amazon_music') if link_result.get('album_aggregated') else None
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

def run_scrape(url: str, artifacts_dir: Path) -> Path:
    """
    Stage 1: Scrape playlist from URL and save to JSON artifact.
    
    Args:
        url: Playlist URL to scrape
        artifacts_dir: Directory to save artifacts
    
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
        stem = derive_artifact_stem(playlist_data.get("meta", {}))
        output_path = artifacts_dir / f"{stem}.playlist.json"
        
        # Save playlist JSON
        save_json(playlist_data, output_path)
        
        print(f"✓ Successfully scraped playlist: {playlist_title}")
        print(f"✓ Found {track_count} tracks")
        print(f"✓ Saved to: {output_path}")
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
        
        # Derive artifact filename (use same stem as playlist)
        stem = derive_artifact_stem(playlist_data.get("meta", {}))
        output_path = artifacts_dir / f"{stem}.match.json"
        
        # Save match report
        save_json(match_result, output_path)
        
        print(f"✓ Matched {found} of {total} tracks")
        if missing > 0:
            print(f"⚠ {missing} tracks not found in library")
        else:
            print("✓ All tracks found in library!")
        print(f"✓ Saved to: {output_path}")
        print()
        
        return output_path
        
    except Exception as e:
        print(f"Error matching tracks: {e}")
        raise


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
    
    # Print track list that will be enriched
    enrich_type = "MISSING TRACKS" if missing_only else "ALL TRACKS"
    print_track_list(tracks_to_enrich, f"{enrich_type} TO ENRICH ({len(tracks_to_enrich)} tracks)")
    
    print(f"Enriching {len(tracks_to_enrich)} track(s) with streaming links...")
    print()
    
    session = requests.Session()
    links_found = 0
    
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
                
                # Attach link result to track
                if link_result.get("ok"):
                    track["share_links"] = link_result.get("aggregated", {}).get("targets", {})
                    track["songlink_page"] = link_result.get("aggregated", {}).get("page_url")
                    track["link_seed"] = link_result.get("seed")
                    
                    # Store album links if available
                    album_aggregated = link_result.get("album_aggregated", {})
                    if album_aggregated:
                        track["album_share_links"] = album_aggregated.get("targets", {})
                    else:
                        track["album_share_links"] = {}
                    
                    links_found += 1
                else:
                    track["share_links"] = {}
                    track["album_share_links"] = {}
                    track["songlink_page"] = None
                    track["link_seed"] = None
            except Exception:
                # Silently handle errors
                track["share_links"] = {}
                track["album_share_links"] = {}
                track["songlink_page"] = None
                track["link_seed"] = None
        
        # Derive artifact filename (use same stem as match)
        playlist_data = match_result.get("playlist_data", {})
        stem = derive_artifact_stem(playlist_data.get("meta", {}))
        output_path = artifacts_dir / f"{stem}.enriched.json"
        
        # Save enriched match report
        save_json(match_result, output_path)
        
        print()
        print(f"✓ Found links for {links_found} of {len(tracks_to_enrich)} track(s)")
        print(f"✓ Saved to: {output_path}")
        print()
        
        # Print enriched track list with links
        enrich_type = "ENRICHED MISSING TRACKS" if missing_only else "ENRICHED TRACKS"
        print_track_list_with_links(tracks_to_enrich, f"{enrich_type} ({len(tracks_to_enrich)} tracks)")
        
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
    
    # Stage 1: Scrape
    playlist_json_path = run_scrape(url, artifacts_dir)
    playlist_data = load_json(playlist_json_path)
    
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
    print_title("STEP 4: CREATE PLAYLIST")
    print("Enter the target location where the playlist folder should be created.")
    print("Example: ~/Desktop or /Users/username/Desktop")
    print()
    
    target_dir = prompt_user("Target directory")
    if not target_dir:
        print("Error: Target directory is required.")
        sys.exit(1)
    
    target_path = Path(target_dir).expanduser()
    if not target_path.exists():
        print(f"Error: Target directory does not exist: {target_path}")
        sys.exit(1)
    
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
            print(f"Available {expected_json_type or 'artifact'} files in {ARTIFACTS_DIR}:")
            for i, artifact in enumerate(artifacts[:10], 1):  # Show up to 10 most recent
                print(f"  {i}. {artifact.name}")
            if len(artifacts) > 10:
                print(f"  ... and {len(artifacts) - 10} more")
            print()
            if prompt_yes_no("Use one of these files?", default=False):
                while True:
                    try:
                        choice_str = prompt_user(f"Enter number (1-{min(10, len(artifacts))}) or path")
                        if not choice_str:
                            break
                        # Try to parse as number
                        try:
                            choice_num = int(choice_str)
                            if 1 <= choice_num <= min(10, len(artifacts)):
                                return artifacts[choice_num - 1].resolve()
                            else:
                                print(f"Please enter a number between 1 and {min(10, len(artifacts))}")
                                continue
                        except ValueError:
                            # Not a number, treat as path
                            break
                    except (KeyboardInterrupt, EOFError):
                        break
    
    while True:
        path_str = prompt_user(prompt_text)
        if not path_str:
            print(f"Error: {file_type.capitalize()} path is required.")
            if not prompt_yes_no("Try again?", default=True):
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
            raise SystemExit(0)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"Error: {e}")
            if prompt_yes_no("Try again?", default=True):
                continue
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
    print("7. Quit")
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
        
        run_scrape(url, ARTIFACTS_DIR)
        print("\n✓ Stage 1 completed successfully!")
        return True
        
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
        
        target_dir_str = prompt_user("Enter target directory for playlist folder")
        if not target_dir_str:
            print("Error: Target directory is required.")
            return prompt_yes_no("Return to main menu?", default=True)
        
        target_dir = Path(target_dir_str).expanduser()
        try:
            target_dir = validate_file_path(target_dir, "directory")
        except FileNotFoundError as e:
            print(f"Error: {e}")
            return prompt_yes_no("Return to main menu?", default=True)
        
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
    print("Please enter a number between 1 and 7.")
    print()
    return prompt_yes_no("Return to menu?", default=True)


def run_main_menu_loop() -> None:
    """
    Run the main menu loop until user quits.
    
    This function handles the menu display, choice routing, and loop control.
    """
    while True:
        display_main_menu()
        choice = prompt_user("Select option (1-7)", "1").strip()
        
        if choice == "7":
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
        else:
            should_continue = handle_invalid_choice(choice)
        
        if not should_continue:
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
