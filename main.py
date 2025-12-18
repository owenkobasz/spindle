#!/usr/bin/env python3
"""
WPRB Playlist Scraper - Main Entry Point

This script provides an interactive workflow to:
1. Scrape a playlist from a URL
2. Match tracks against your local music library
3. Create a playlist folder with numbered tracks
"""

import sys
from pathlib import Path

from scraper import playlist_scraper
from match_playlist_to_library import match_playlist_to_library
from create_playlist import export_playlist_copies


def print_separator(char="=", length=60):
    """Print a visual separator line."""
    print(char * length)


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
    Prompt user for library location.
    
    Returns:
        Tuple of (base_folder, library_subpath)
    """
    print_separator()
    print("LIBRARY LOCATION")
    print_separator()
    print("Enter the path to your music library.")
    print("Examples:")
    print("  - If library is at /Volumes/Music Library, enter that path")
    print("  - If library is at /Users/username/Music/Library, enter /Users/username and subpath Music/Library")
    print()
    
    base = prompt_user("Base folder")
    if not base:
        print("Error: Base folder is required.")
        sys.exit(1)
    
    # Check if base folder exists
    base_path = Path(base).expanduser()
    if not base_path.exists():
        print(f"Error: Base folder does not exist: {base_path}")
        sys.exit(1)
    
    # Ask for subpath if base might not be the library root
    subpath = prompt_user("Library subpath (press Enter if base folder IS the library)", "")
    
    return str(base_path), subpath


def display_missing_tracks(match_result: dict) -> list[dict]:
    """
    Display missing tracks and return list of missing track info.
    
    Returns:
        List of track dictionaries that are missing
    """
    missing = [r for r in match_result["results"] if r["match_status"] == "missing"]
    
    if not missing:
        return []
    
    print_separator()
    print(f"MISSING TRACKS ({len(missing)} of {match_result['summary']['total_tracks']})")
    print_separator()
    
    for i, track in enumerate(missing, 1):
        print(f"{i}. {track['artist']} - {track['song']}")
        if track.get('album'):
            print(f"   Album: {track['album']}")
        if track.get('candidate_paths'):
            print(f"   Candidates found:")
            for path in track['candidate_paths'][:3]:  # Show first 3 candidates
                print(f"     - {Path(path).name}")
        print()
    
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
    
    print_separator()
    print("CREATE ARTIST DIRECTORIES")
    print_separator()
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


def confirm_skip_tracks(still_missing: list[dict]) -> list[dict]:
    """
    Ask user to confirm skipping each track that still can't be found.
    
    Args:
        still_missing: List of tracks that are still missing after re-matching
    
    Returns:
        List of tracks that user confirmed to skip
    """
    if not still_missing:
        return []
    
    print_separator()
    print("CONFIRM SKIPPING TRACKS")
    print_separator()
    print(f"The following {len(still_missing)} tracks still cannot be found:")
    print("You can choose to skip each track or cancel the operation.")
    print()
    
    tracks_to_skip = []
    tracks_to_keep = []
    
    for i, track in enumerate(still_missing, 1):
        artist = track.get('artist', 'Unknown')
        song = track.get('song', 'Unknown')
        album = track.get('album', '')
        
        print(f"{i}/{len(still_missing)}. {artist} - {song}")
        if album:
            print(f"    Album: {album}")
        
        if prompt_yes_no("    Skip this track?", default=False):
            tracks_to_skip.append(track)
            print("    → Will be skipped")
        else:
            tracks_to_keep.append(track)
            print("    → Will be kept (operation will be cancelled)")
        print()
    
    if tracks_to_keep:
        print(f"⚠ {len(tracks_to_keep)} tracks will not be skipped.")
        print("Operation cancelled. Please add these tracks to your library and try again.")
        return None  # Signal to cancel
    
    return tracks_to_skip


def main():
    """Main workflow function."""
    print_separator()
    print("WPRB PLAYLIST SCRAPER")
    print_separator()
    print()
    
    # Step 1: Get playlist URL
    print_separator()
    print("STEP 1: PLAYLIST URL")
    print_separator()
    url = prompt_user("Enter playlist URL")
    if not url:
        print("Error: URL is required.")
        sys.exit(1)
    
    # Step 2: Scrape playlist
    print_separator()
    print("STEP 2: SCRAPING PLAYLIST")
    print_separator()
    print(f"Scraping: {url}")
    print("Please wait...")
    
    try:
        playlist_data = playlist_scraper(url)
        track_count = playlist_data.get("meta", {}).get("track_count", 0)
        playlist_title = playlist_data.get("meta", {}).get("playlist_title", "Unknown")
        print(f"✓ Successfully scraped playlist: {playlist_title}")
        print(f"✓ Found {track_count} tracks")
    except Exception as e:
        print(f"Error scraping playlist: {e}")
        sys.exit(1)
    
    # Step 3: Get library location and match tracks
    print_separator()
    print("STEP 3: MATCHING TRACKS TO LIBRARY")
    print_separator()
    
    base_folder, library_subpath = get_library_path()
    
    print()
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
        
        found = match_result["summary"]["found"]
        missing = match_result["summary"]["missing"]
        total = match_result["summary"]["total_tracks"]
        
        print(f"✓ Matched {found} of {total} tracks")
        
        if missing > 0:
            print(f"⚠ {missing} tracks not found in library")
        else:
            print("✓ All tracks found in library!")
    except Exception as e:
        print(f"Error matching tracks: {e}")
        sys.exit(1)
    
    # Step 4: Handle missing tracks
    missing_tracks = display_missing_tracks(match_result)
    
    if missing_tracks:
        print_separator()
        print("MISSING TRACKS DETECTED")
        print_separator()
        
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
            
            print(f"ℹ {len(confirmed_skips)} tracks will be skipped in playlist creation.")
            print()
    
    # Step 5: Get target location and create playlist
    print_separator()
    print("STEP 4: CREATE PLAYLIST")
    print_separator()
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
    
    print()
    print("Creating playlist...")
    print("Please wait...")
    
    try:
        result = export_playlist_copies(
            data=playlist_data,
            base_folder=base_folder,
            target_dir=str(target_path),
            library_subpath=library_subpath,
            make_subfolder=True,
            overwrite=False,
        )
        
        copied = result["summary"]["copied"]
        total = result["summary"]["total_tracks"]
        dest_folder = result["destination_folder"]
        
        print_separator()
        print("✓ PLAYLIST CREATED SUCCESSFULLY!")
        print_separator()
        print(f"Location: {dest_folder}")
        print(f"Tracks copied: {copied} of {total}")
        print(f"Manifest: {Path(dest_folder) / 'manifest.json'}")
        print()
        print("Playlist is ready to use!")
        
    except Exception as e:
        print(f"Error creating playlist: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
