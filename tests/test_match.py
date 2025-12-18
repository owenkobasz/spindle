#!/usr/bin/env python3
"""Test script for match_playlist_to_library function."""

import json
from match_playlist_to_library import match_playlist_to_library

# Load sample playlist data
with open("sample_data/sample_playlist_1", "r") as f:
    playlist_data = json.load(f)

# Test the function
# MODIFY: Update these paths to match your library location
# Example: If library is at /Volumes/Music Library, use that path
#          If library is at /Users/username/Music/Library, use base_folder="/Users/username" and library_subpath="Music/Library"
result = match_playlist_to_library(
    data=playlist_data,
    base_folder="/path/to/your/library",  # MODIFY: Update this path
    library_subpath="",  # MODIFY: Update if needed
    include_candidates=True,
    max_candidates=5,
)

# Print summary
print("=" * 60)
print("MATCHING SUMMARY")
print("=" * 60)
print(f"Library root: {result['summary']['library_root']}")
print(f"Total tracks: {result['summary']['total_tracks']}")
print(f"Found: {result['summary']['found']}")
print(f"Missing: {result['summary']['missing']}")
print()

# Print NewDad tracks specifically
print("=" * 60)
print("NEWDAD TRACKS (should have matches)")
print("=" * 60)
for track in result['results']:
    if track['artist'].lower() == 'newdad':
        print(f"\nTime: {track['time']}")
        print(f"Artist: {track['artist']}")
        print(f"Album: {track['album']}")
        print(f"Song: {track['song']}")
        print(f"Status: {track['match_status']}")
        if track['matched_paths']:
            print(f"Matched paths:")
            for path in track['matched_paths']:
                print(f"  - {path}")
        if track.get('candidate_paths'):
            print(f"Candidate paths:")
            for path in track['candidate_paths']:
                print(f"  - {path}")
        print()

# Print all found tracks
print("=" * 60)
print("ALL FOUND TRACKS")
print("=" * 60)
found_tracks = [t for t in result['results'] if t['match_status'] == 'found']
for track in found_tracks:
    print(f"{track['artist']} - {track['song']} ({track['album']})")
    for path in track['matched_paths']:
        print(f"  -> {path}")
    print()



