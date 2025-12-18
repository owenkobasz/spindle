#!/usr/bin/env python3
"""Test script for create_playlist.py export_playlist_copies function."""

import json
from create_playlist import export_playlist_copies

# Load sample playlist data
with open("sample_data/sample_playlist_1", "r") as f:
    playlist_data = json.load(f)

# Test the function
# MODIFY: Update these paths to match your system
print("=" * 60)
print("CREATING PLAYLIST")
print("=" * 60)
print(f"Source: sample_playlist_1")
print(f"Library: /path/to/your/library")  # MODIFY: Update this path
print(f"Target: /path/to/target/location")  # MODIFY: Update this path
print()

result = export_playlist_copies(
    data=playlist_data,
    base_folder="/path/to/your/library",  # MODIFY: Update this path
    target_dir="/path/to/target/location",  # MODIFY: Update this path
    library_subpath="",  # MODIFY: Update if needed
    make_subfolder=True,
    overwrite=False,
)

# Print summary
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Destination folder: {result['destination_folder']}")
print(f"Total tracks: {result['summary']['total_tracks']}")
print(f"Copied: {result['summary']['copied']}")
print(f"Missing: {result['summary']['missing']}")
print()

# Print first few copied files
print("=" * 60)
print("COPIED FILES (first 10)")
print("=" * 60)
copied_items = [r for r in result['results'] if r.get('copied_path')]
for item in copied_items[:10]:
    print(f"{item['order']:02d}. {item['artist']} - {item['song']}")
    print(f"     -> {item['copied_path']}")
    print()

# Print missing tracks if any
missing_items = [r for r in result['results'] if not r.get('copied_path')]
if missing_items:
    print("=" * 60)
    print("MISSING TRACKS")
    print("=" * 60)
    for item in missing_items:
        print(f"{item['order']:02d}. {item['artist']} - {item['song']} ({item['album']})")
    print()

print("=" * 60)
print("Manifest saved to:", result['destination_folder'] + "/manifest.json")
print("=" * 60)


