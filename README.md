# Spindle

**Spindle** is part of a broader effort to move away from streaming platforms and rebuild a personal, local music library. The project started from a simple need: I wanted an easy way to turn playlists from my favorite radio shows into organized, offline copies that live alongside my own music collection.

Lately, I’ve been increasingly appreciative of **human-curated content**, and public radio remains one of the strongest places where that still thrives. Spindle is designed to scrape radio playlists, match tracks against a local music library, help identify missing pieces, and export ordered playlist folders to a destination of your choice.

I’m currently using it to load SD cards as playlist or album “cartridges” for a FiiO Echo Mini — essentially modern cartridge-CDs — but the workflow is general enough to apply to other devices and other public playlists as well.

**TL;DR:**
A console-based Python tool that scrapes playlists from WPRB (and other Spinitron-based sites), matches tracks against a local music library, and creates organized playlist folders with numbered tracks.

---

### How it works

At a high level, Spindle:

* Scrapes playlist metadata from Spinitron-based radio sites
* Normalizes and matches tracks against a local library organized by Artist/Album/Track
* Copies matched tracks into a new folder in playlist order
* Generates manifests and metadata for auditing and reuse

One pain point I didn’t initially know how to solve was generating **streaming service reference links** for tracks and albums. Most major streaming platforms don’t expose public search APIs and are notoriously difficult to scrape reliably.

The solution ended up being surprisingly clean: Spindle sends track metadata to Deezer’s public API to obtain a canonical track URL, then passes that URL to a link-aggregator API (Odesli) to retrieve equivalent links for other platforms. iTunes’ public Search API is used as a fallback when Deezer fails. This approach avoids brittle scraping and works remarkably well across services like Amazon Music, Tidal, Deezer, and others.

---

### Notes on the build process

This project was also an experiment in *vibe coding* — intentionally building a small, focused tool with the help of GPT, Cursor, and Notion. My workflow was roughly:

* Break the idea into discrete components and outline them in Notion
* Use GPT to draft initial versions of each component
* Assemble a local project and define a clear main execution path
* Use Cursor to connect pieces, refactor, and create documentation 

The result came together faster and more cleanly than I expected, and I’m currently working on a longer blog post that dives deeper into this workflow.

---

### Limitations and next steps

Like most projects that work with natural language data, Spindle is only as good as the metadata it consumes. I’ve done my best to normalize names, punctuation, and formatting, but mismatches are inevitable.

My next step is importing my older music archive into the same drive and building a companion tool to help standardize and clean that library. Many of those files date back to the early 2000s, and their organization is… optimistic at best.

---

## Features

- **Playlist Scraping**: Scrape playlist data from WPRB and other Spinitron-based websites
- **Smart Library Matching**: Intelligently match playlist tracks to your local music library with flexible matching that handles:
  - Filenames with artist names (e.g., "Artist - Song.flac")
  - Track numbers in filenames (e.g., "02. Song.flac")
  - Album name variations (e.g., "Album - EP" vs "Album")
  - Case and punctuation differences
- **Music Cataloging**: Automatically organize newly downloaded music files into your library:
  - Extracts metadata from audio tags (ID3, Vorbis, iTunes)
  - Falls back to filename/path parsing when tags are missing
  - Organizes files into `Artist/Album/Track` structure
  - Handles duplicates intelligently
  - Supports both move and copy operations
- **Interactive Workflow**: Step-by-step terminal interface that guides you through the process
- **Missing Track Handling**: 
  - Automatically create artist directories for missing tracks
  - Shows streaming service links (Amazon Music, Tidal, Deezer, SoundCloud, Qobuz) for missing tracks
  - Confirm skipping tracks that can't be found
- **Streaming Link Enrichment**: 
  - Finds links for tracks across multiple streaming platforms
  - Uses Deezer and iTunes APIs with Odesli/Songlink aggregation
  - Caches results to avoid redundant API calls
  - Supports both track and album links
- **Playlist Creation**: Copy matched tracks to a new folder with numbered filenames in playlist order
- **Artifacts System**: Saves intermediate JSON files for review and reuse
- **Staged Workflow**: Run stages independently or use the full guided pipeline

## Installation

### Requirements

- Python 3.8 or higher
- pip

### Setup

1. Clone this repository:
```bash
git clone <repository-url>
cd spindle
```

2. Create and activate a virtual environment (recommended):
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Quick Start

Run the main script for an interactive workflow:

```bash
python3 main.py
```

The script presents a main menu with eight options:

**Option 1: Scrape playlist (save JSON artifact)**
- Scrapes a playlist from a URL and saves it as a JSON artifact
- Prompts for a custom name for the playlist artifact
- Saves to `artifacts/` directory with format: `YYYY-MM-DD_playlist-name.playlist.json`

**Option 2: Match playlist JSON to library (save match report)**
- Matches tracks from a playlist JSON artifact against your library
- Shows which tracks were found and which are missing
- Saves match report as: `YYYY-MM-DD_playlist-name.match.json`

**Option 3: Enrich missing tracks with streaming links (save enriched report)**
- Adds streaming service links (Amazon Music, Tidal, Deezer, SoundCloud, Qobuz) to tracks
- Can enrich all tracks or only missing tracks
- Uses cached results to avoid redundant API calls
- Saves enriched report as: `YYYY-MM-DD_playlist-name.enriched.json`

**Option 4: Export playlist folder (from match report or playlist JSON)**
- Creates a playlist folder with numbered tracks in playlist order
- Can use either a match report or playlist JSON as input
- Automatically skips missing tracks if confirmed
- Creates a manifest.json file with metadata

**Option 5: Catalog new music into library**
- Scans a drop location for music files
- Extracts metadata from audio tags or infers from filenames
- Organizes files into `Artist/Album/Track` structure
- Supports move or copy operations
- Handles duplicates intelligently

**Option 6: Run full pipeline (guided)**
- Runs stages 1-4 end-to-end with guided interaction
- Handles missing tracks interactively
- Shows streaming links for missing tracks
- Offers to create artist directories
- Allows re-matching after adding tracks

**Option 7: Clean up old playlist artifacts**
- Lists all saved playlist artifacts grouped by playlist
- Allows selective deletion of old artifacts
- Useful for managing disk space

**Option 8: Quit**
- Exits the program

### Artifacts System

Spindle uses an artifacts system to save intermediate results, allowing you to:
- Re-run stages independently without starting over
- Review and modify data between stages
- Build up playlists incrementally
- Keep a history of your work

Artifacts are saved in the `artifacts/` directory with the following naming:
- `YYYY-MM-DD_playlist-name.playlist.json` - Scraped playlist data
- `YYYY-MM-DD_playlist-name.match.json` - Match results with library
- `YYYY-MM-DD_playlist-name.enriched.json` - Match results with streaming links

### Staged Workflow

You can run the workflow in stages:
1. **Stage 1**: Scrape playlist → saves `.playlist.json`
2. **Stage 2**: Match to library → saves `.match.json`
3. **Stage 3**: Enrich with links → saves `.enriched.json`
4. **Stage 4**: Export playlist folder → uses any of the above JSON files

This allows you to pause, review, and resume at any stage.

### Library Structure

The tool expects your music library to follow this structure:
```
Library/
  Artist Name/
    Album Name/
      Track Name.ext
```

### Example Workflows

**Full Guided Pipeline:**
```bash
$ python3 main.py

   ███████╗██████╗ ██╗███╗   ██╗██████╗ ██╗     ███████╗
   ██╔════╝██╔══██╗██║████╗  ██║██╔══██╗██║     ██╔════╝
   ███████╗██████╔╝██║██╔██╗ ██║██║  ██║██║     █████╗  
   ╚════██║██╔═══╝ ██║██║╚██╗██║██║  ██║██║     ██╔══╝  
   ███████║██║     ██║██║ ╚████║██████╔╝███████╗███████╗
   ╚══════╝╚═╝     ╚═╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚══════╝

            curated radio → local playlists

============================================================
MAIN MENU
============================================================
1. Scrape playlist (save JSON artifact)
2. Match playlist JSON to library (save match report)
3. Enrich missing tracks with streaming links (save enriched report)
4. Export playlist folder (from match report or playlist JSON)
5. Catalog new music into library
6. Run full pipeline (guided)
7. Clean up old playlist artifacts
8. Quit

Select option (1-8) [1]: 6

============================================================
GUIDED PIPELINE
============================================================
...
```

**Staged Workflow:**
```bash
# Stage 1: Scrape playlist
Select option (1-8) [1]: 1
Enter playlist URL: https://playlists.wprb.com/WPRB/pl/21686552/Lady-Love
Playlist name [lady-love]: 
✓ Saved to: artifacts/2025-12-17_lady-love.playlist.json

# Stage 2: Match to library
Select option (1-8) [1]: 2
Enter path to playlist JSON file: artifacts/2025-12-17_lady-love.playlist.json
✓ Matched 25 of 31 tracks
✓ Saved to: artifacts/2025-12-17_lady-love.match.json

# Stage 3: Enrich missing tracks
Select option (1-8) [1]: 3
Enter path to match JSON file: artifacts/2025-12-17_lady-love.match.json
Enrich only missing tracks? [Y/n]: Y
Enriching tracks: 100%|████████████| 6/6 [00:15<00:00,  2.5s/track]
✓ Found links for 5 of 6 track(s)
✓ Saved to: artifacts/2025-12-17_lady-love.enriched.json

# Stage 4: Export playlist folder
Select option (1-8) [1]: 4
Enter path to match JSON or playlist JSON file: artifacts/2025-12-17_lady-love.match.json
Target directory: ~/Desktop
✓ Playlist created successfully!
✓ Location: ~/Desktop/2025-12-17 - Lady-Love
```

**Music Cataloging:**
```bash
Select option (1-8) [1]: 5

============================================================
CATALOG NEW MUSIC
============================================================
Enter drop location (where new music files are): ~/Downloads/Music
Move files to library? (No = copy files) [Y/n]: Y
Skip files that already exist in library? [Y/n]: Y

Scanning for audio files...
Cataloging files: 100%|████████████| 15/15 [00:03<00:00,  4.2file/s]
✓ Cataloged: 15 files
ℹ Skipped: 2 files (duplicates)
```

### Command Line Options

#### Using Individual Modules

You can also use the modules independently:

**Scrape a playlist:**
```python
from scraper import playlist_scraper

data = playlist_scraper("https://playlists.wprb.com/WPRB/pl/21686552/Lady-Love")
```

**Match tracks to library:**
```python
from match_playlist_to_library import match_playlist_to_library

result = match_playlist_to_library(
    data=playlist_data,
    base_folder="/path/to/library",
    library_subpath="",  # or "Music/Library" if needed
)
```

**Create playlist folder:**
```python
from create_playlist import export_playlist_copies

result = export_playlist_copies(
    data=playlist_data,
    base_folder="/path/to/library",
    target_dir="/path/to/output",
    library_subpath="",
)
```

**Catalog new music:**
```python
from catalog_music import catalog_music

result = catalog_music(
    drop_location="/path/to/downloads",
    library_root="/path/to/library",
    move_files=True,  # False to copy instead
    skip_duplicates=True,
)
```

## Project Structure

```
spindle/
├── main.py                          # Main interactive script with menu
├── scraper.py                        # Playlist scraping functionality
├── match_playlist_to_library.py     # Library matching logic
├── create_playlist.py                # Playlist folder creation
├── catalog_music.py                  # Music cataloging and organization
├── link_finder.py                    # Streaming link finder (multi-platform)
├── requirements.txt                  # Python dependencies
├── artifacts/                        # Saved playlist artifacts (JSON files)
│   ├── YYYY-MM-DD_name.playlist.json
│   ├── YYYY-MM-DD_name.match.json
│   └── YYYY-MM-DD_name.enriched.json
├── link_cache.json                   # Cached streaming link results
├── sample_data/                      # Sample playlist data for testing
│   └── sample_playlist_1
├── tests/                            # Test suite
│   ├── test_scraper.py
│   ├── test_match_playlist_to_library.py
│   ├── test_create_playlist.py
│   └── TEST_README.md
└── README.md                         # This file
```

## Features in Detail

### Smart Matching

The matching algorithm handles various naming inconsistencies:

- **Artist name in filename**: Matches "Artist - Song.flac" when looking for "Song"
- **Track numbers**: Handles "02. Song.flac" format
- **Album variations**: Matches "Album - EP" to "Album"
- **Punctuation differences**: Normalizes quotes, dashes, and special characters
- **Case insensitive**: Matches regardless of capitalization

### Missing Track Handling

When tracks aren't found:
1. The script lists all missing tracks with candidate suggestions
2. Shows streaming service links for tracks and albums (Amazon Music, Tidal, Deezer, SoundCloud, Qobuz) when available
3. Offers to create artist directories in your library
4. After you add tracks, re-matches to verify
5. Allows you to confirm skipping tracks that still can't be found

### Streaming Link Enrichment

The link enrichment feature uses a multi-step process:
1. **Seed Lookup**: Searches Deezer API for track matches (falls back to iTunes if needed)
2. **Link Aggregation**: Passes seed URL to Odesli/Songlink API to get links for multiple platforms
3. **Caching**: Results are cached locally in `link_cache.json` to avoid redundant API calls
4. **Platform Support**: Returns links for Amazon Music, Tidal, Deezer, SoundCloud, and Qobuz

The enrichment can be run independently (Stage 3) or as part of the guided pipeline.

### Music Cataloging

The cataloging feature automatically organizes newly downloaded music:

- **Metadata Extraction**: Reads ID3 tags (MP3), Vorbis comments (FLAC, OGG), and iTunes tags (M4A)
- **Smart Fallback**: When tags are missing, infers metadata from:
  - File path structure (e.g., `Artist/Album/Track.mp3`)
  - Filename patterns (e.g., `Artist - Track.mp3`, `01. Track.mp3`)
- **Duplicate Detection**: Checks if files already exist in library before cataloging
- **Flexible Operations**: Choose to move or copy files
- **Track Numbering**: Preserves track numbers from tags or filenames

## Testing

Run the test suite:

```bash
# Install pytest if not already installed
pip install pytest

# Run all tests
pytest test_scraper.py test_match_playlist_to_library.py -v

# Run specific test file
pytest test_scraper.py -v
```

See `TEST_README.md` for more testing information.

## Configuration

### Library Path

The tool prompts for your library location, but you can also set defaults in the code if desired.

### Supported Audio Formats

The tool supports these audio file formats:
- `.mp3`, `.m4a`, `.flac`, `.wav`, `.aiff`, `.aif`, `.ogg`, `.opus`, `.alac`

### Dependencies

- `requests` - HTTP requests for scraping and API calls
- `beautifulsoup4` - HTML parsing for playlist scraping
- `mutagen` - Audio metadata extraction (for cataloging)
- `tqdm` - Progress bars for long-running operations
- `pytest` - Testing framework (optional, for development)

## Troubleshooting

### Tracks Not Matching

If tracks aren't matching:
1. Check that your library follows the `Artist/Album/Track.ext` structure
2. Verify filenames don't have unusual characters
3. Check the candidate suggestions - they may help identify naming issues
4. Try renaming files to match the expected format

### Playlist Scraping Fails

If scraping fails:
1. Verify the URL is accessible
2. Check that the site uses Spinitron (the scraper is designed for Spinitron-based sites)
3. The site structure may have changed - check the HTML selectors in `scraper.py`

### Cataloging Issues

If cataloging isn't working:
1. Ensure `mutagen` is installed: `pip install mutagen`
2. Check that audio files have readable metadata tags
3. Files without tags will use filename/path inference - ensure filenames are descriptive
4. Verify the drop location path is correct and accessible
5. Check that the library root path is correct

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- Built for scraping WPRB playlists (https://playlists.wprb.com)
- Uses BeautifulSoup for HTML parsing
- Uses Mutagen for audio metadata extraction
- Uses Deezer and iTunes APIs for seed URL lookup
- Uses Odesli/Songlink API for multi-platform link aggregation
- Designed to work with Spinitron-based playlist systems

