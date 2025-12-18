# Spindle

Spindle is part of a larger effort to move away from streaming and rebuild a local music library. Its scope is very niche and small at this point because I basically wanted to have a way to easily create local copies of playlists from my favoirte radio shows. I've been increasingly appreciative of human curated content recently and public radio is one of the most powerful places for that. This app is designed to scrape a playlist, help you fill in any gaps within your local library, and then export a copy to a given place. I'm using it for loading SD cards to be used as playlist/album holders (cartridge-CDs if you will) for a Fiio Echo Mini, but the process is pretty general and it whould work with other public playlists as well.

TL/DR: A Python tool to scrape playlists from WPRB (and other Spinitron-based playlist sites), match tracks against your local music library, and create organized playlist folders with numbered tracks.

## Features

- **Playlist Scraping**: Scrape playlist data from WPRB and other Spinitron-based websites
- **Smart Library Matching**: Intelligently match playlist tracks to your local music library with flexible matching that handles:
  - Filenames with artist names (e.g., "Artist - Song.flac")
  - Track numbers in filenames (e.g., "02. Song.flac")
  - Album name variations (e.g., "Album - EP" vs "Album")
  - Case and punctuation differences
- **Interactive Workflow**: Step-by-step terminal interface that guides you through the process
- **Missing Track Handling**: 
  - Automatically create artist directories for missing tracks
  - Confirm skipping tracks that can't be found
- **Playlist Creation**: Copy matched tracks to a new folder with numbered filenames in playlist order

## Installation

### Requirements

- Python 3.8 or higher
- pip

### Setup

1. Clone this repository:
```bash
git clone <repository-url>
cd WPRB-Scraper
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Quick Start

Run the main script for an interactive workflow:

```bash
python3 main.py
```

The script will guide you through:
1. Entering the playlist URL
2. Scraping the playlist
3. Matching tracks to your library
4. Handling missing tracks
5. Creating the playlist folder

### Library Structure

The tool expects your music library to follow this structure:
```
Library/
  Artist Name/
    Album Name/
      Track Name.ext
```

### Example Workflow

```bash
$ python3 main.py

============================================================
WPRB PLAYLIST SCRAPER
============================================================

============================================================
STEP 1: PLAYLIST URL
============================================================
Enter playlist URL: https://playlists.wprb.com/WPRB/pl/21686552/Lady-Love

============================================================
STEP 2: SCRAPING PLAYLIST
============================================================
Scraping: https://playlists.wprb.com/WPRB/pl/21686552/Lady-Love
Please wait...
✓ Successfully scraped playlist: WPRB Princeton 103.3 FM
✓ Found 31 tracks

...
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

## Project Structure

```
WPRB-Scraper/
├── main.py                          # Main interactive script
├── scraper.py                        # Playlist scraping functionality
├── match_playlist_to_library.py     # Library matching logic
├── create_playlist.py                # Playlist folder creation
├── requirements.txt                  # Python dependencies
├── sample_data/                      # Sample playlist data for testing
│   └── sample_playlist_1
├── test_scraper.py                   # Tests for scraper
├── test_match_playlist_to_library.py # Tests for matching
├── test_create_playlist.py           # Tests for playlist creation
└── TEST_README.md                    # Testing documentation
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
2. Offers to create artist directories in your library
3. After you add tracks, re-matches to verify
4. Allows you to confirm skipping tracks that still can't be found

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

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

[Add your license here]

## Acknowledgments

- Built for scraping WPRB playlists (https://playlists.wprb.com)
- Uses BeautifulSoup for HTML parsing
- Designed to work with Spinitron-based playlist systems

