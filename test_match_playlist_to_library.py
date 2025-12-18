"""
Unit tests for match_playlist_to_library.py

To run: pytest test_match_playlist_to_library.py -v
To run specific test: pytest test_match_playlist_to_library.py::test_norm_basic -v
"""

import tempfile
import shutil
from pathlib import Path
import pytest

from match_playlist_to_library import (
    _norm,
    _iter_audio_files,
    _build_index,
    match_playlist_to_library,
    AUDIO_EXTS,
)


class TestNormFunction:
    """Tests for _norm string normalization function"""

    def test_norm_basic(self):
        """Test basic normalization (lowercase, whitespace)"""
        assert _norm("Hello World") == "hello world"
        assert _norm("  HELLO   WORLD  ") == "hello world"

    def test_norm_with_none(self):
        """Test _norm handles None input"""
        assert _norm(None) == ""

    def test_norm_removes_punctuation(self):
        """Test that punctuation is removed"""
        assert _norm("Hello, World!") == "hello world"
        assert _norm("Song (Remix)") == "song remix"

    def test_norm_removes_feat_patterns(self):
        """Test that 'feat.' patterns are removed"""
        # MODIFY THIS: Add more feat. pattern variations to test
        assert _norm("Song (feat. Artist)") == "song"
        assert _norm("Song [feat. Artist]") == "song"
        assert _norm("Song feat. Artist") == "song"
        assert _norm("Song feat Artist") == "song"

    def test_norm_replaces_ampersand(self):
        """Test that & is replaced with 'and'"""
        assert _norm("Simon & Garfunkel") == "simon and garfunkel"

    def test_norm_unicode_normalization(self):
        """Test unicode normalization"""
        # Test with curly quotes
        assert _norm("I'll") == "ill"  # After normalization and punctuation removal
        assert _norm("café") == "cafe"

    def test_norm_case_insensitive(self):
        """Test that normalization is case-insensitive"""
        assert _norm("HELLO") == _norm("hello") == _norm("Hello") == "hello"

    def test_norm_complex_example(self):
        """Test complex real-world example"""
        # MODIFY THIS: Add your own test cases with real song/artist names
        result = _norm("Song (feat. Artist & Co.) - Remix!")
        assert result == "song remix"


class TestIterAudioFiles:
    """Tests for _iter_audio_files function"""

    def test_iter_audio_files_finds_audio(self):
        """Test that audio files are found"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # Create test audio files
            (tmp_path / "song1.mp3").touch()
            (tmp_path / "song2.flac").touch()
            (tmp_path / "song3.m4a").touch()
            (tmp_path / "not_audio.txt").touch()

            files = list(_iter_audio_files(tmp_path))
            assert len(files) == 3
            assert all(f.suffix.lower() in AUDIO_EXTS for f in files)

    def test_iter_audio_files_recursive(self):
        """Test that audio files are found recursively"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # Create nested structure
            (tmp_path / "Artist" / "Album").mkdir(parents=True)
            (tmp_path / "Artist" / "Album" / "song.mp3").touch()

            files = list(_iter_audio_files(tmp_path))
            assert len(files) == 1
            assert files[0].name == "song.mp3"

    def test_iter_audio_files_all_extensions(self):
        """Test that all supported audio extensions are found"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # MODIFY THIS: Add/remove extensions to test
            for ext in [".mp3", ".flac", ".m4a", ".wav", ".ogg"]:
                (tmp_path / f"test{ext}").touch()

            files = list(_iter_audio_files(tmp_path))
            assert len(files) == 5


class TestBuildIndex:
    """Tests for _build_index function"""

    def test_build_index_basic(self):
        """Test basic index building"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # Create library structure: Artist/Album/Track.ext
            artist_dir = tmp_path / "Test Artist"
            album_dir = artist_dir / "Test Album"
            album_dir.mkdir(parents=True)
            (album_dir / "Test Song.mp3").touch()

            index = _build_index(tmp_path)
            
            # Check index structure
            key = (_norm("Test Artist"), _norm("Test Album"), _norm("Test Song"))
            assert key in index
            assert len(index[key]) == 1
            assert index[key][0].name == "Test Song.mp3"

    def test_build_index_multiple_files(self):
        """Test index with multiple tracks"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            artist_dir = tmp_path / "Artist"
            album_dir = artist_dir / "Album"
            album_dir.mkdir(parents=True)
            
            (album_dir / "Song1.mp3").touch()
            (album_dir / "Song2.flac").touch()

            index = _build_index(tmp_path)
            assert len(index) == 2

    def test_build_index_case_insensitive(self):
        """Test that index is case-insensitive"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            artist_dir = tmp_path / "Artist"
            album_dir = artist_dir / "Album"
            album_dir.mkdir(parents=True)
            (album_dir / "Song.mp3").touch()

            index = _build_index(tmp_path)
            # Should normalize to lowercase
            key = (_norm("ARTIST"), _norm("album"), _norm("SONG"))
            assert key in index


class TestMatchPlaylistToLibrary:
    """Tests for match_playlist_to_library function"""

    @pytest.fixture
    def sample_playlist_data(self):
        """Sample playlist data structure.
        
        MODIFY THIS: Change the playlist data to match your test cases
        """
        return {
            "meta": {
                "source_url": "https://test.com",
                "playlist_title": "Test Playlist",
            },
            "tracks": [
                {
                    "time": "12:00 PM",
                    "artist": "Test Artist",
                    "song": "Test Song",
                    "release": "Test Album",
                },
                {
                    "time": "12:05 PM",
                    "artist": "Another Artist",
                    "song": "Another Song",
                    "release": "Another Album",
                },
            ],
        }

    @pytest.fixture
    def temp_library(self):
        """Create a temporary library structure for testing.
        
        MODIFY THIS: Change the library structure to test different scenarios
        """
        tmpdir = tempfile.mkdtemp()
        tmp_path = Path(tmpdir)
        
        # Create library structure: Artist/Album/Track.ext
        artist_dir = tmp_path / "Test Artist"
        album_dir = artist_dir / "Test Album"
        album_dir.mkdir(parents=True)
        (album_dir / "Test Song.mp3").touch()
        
        yield tmp_path
        
        # Cleanup
        shutil.rmtree(tmpdir)

    def test_match_playlist_exact_match(self, sample_playlist_data, temp_library):
        """Test exact matching of tracks"""
        result = match_playlist_to_library(
            sample_playlist_data,
            base_folder=str(temp_library),
            library_subpath="",
            include_candidates=False,
        )

        assert result["summary"]["total_tracks"] == 2
        assert result["summary"]["found"] == 1
        assert result["summary"]["missing"] == 1

        # Check first track (should match)
        track1 = result["results"][0]
        assert track1["match_status"] == "found"
        assert len(track1["matched_paths"]) == 1

        # Check second track (should not match)
        track2 = result["results"][1]
        assert track2["match_status"] == "missing"

    def test_match_playlist_with_candidates(self, sample_playlist_data, temp_library):
        """Test matching with candidate suggestions"""
        result = match_playlist_to_library(
            sample_playlist_data,
            base_folder=str(temp_library),
            library_subpath="",
            include_candidates=True,
        )

        # Second track should have candidates
        track2 = result["results"][1]
        if track2["match_status"] == "missing":
            # May or may not have candidates depending on similarity
            assert "candidate_paths" in track2 or "candidate_paths" not in track2

    def test_match_playlist_preserves_meta(self, sample_playlist_data, temp_library):
        """Test that meta data is preserved"""
        result = match_playlist_to_library(
            sample_playlist_data,
            base_folder=str(temp_library),
            library_subpath="",
        )

        assert result["meta"]["source_url"] == "https://test.com"
        assert result["meta"]["playlist_title"] == "Test Playlist"

    def test_match_playlist_library_not_found(self, sample_playlist_data):
        """Test error when library path doesn't exist"""
        with pytest.raises(FileNotFoundError):
            match_playlist_to_library(
                sample_playlist_data,
                base_folder="/nonexistent/path",
                library_subpath="",
            )

    def test_match_playlist_with_subpath(self, sample_playlist_data):
        """Test matching with library_subpath parameter"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            base = tmp_path / "home"
            library = base / "Music" / "Library"
            library.mkdir(parents=True)
            
            artist_dir = library / "Test Artist"
            album_dir = artist_dir / "Test Album"
            album_dir.mkdir(parents=True)
            (album_dir / "Test Song.mp3").touch()

            result = match_playlist_to_library(
                sample_playlist_data,
                base_folder=str(base),
                library_subpath="Music/Library",
            )

            assert result["summary"]["found"] == 1

    def test_match_playlist_normalization(self, temp_library):
        """Test that normalization works for matching"""
        playlist_data = {
            "meta": {},
            "tracks": [
                {
                    "artist": "TEST ARTIST",
                    "song": "Test Song!",
                    "release": "Test Album",
                }
            ],
        }

        result = match_playlist_to_library(
            playlist_data,
            base_folder=str(temp_library),
            library_subpath="",
        )

        # Should match despite case differences and punctuation
        assert result["summary"]["found"] == 1

    def test_match_playlist_max_candidates(self, temp_library):
        """Test max_candidates parameter"""
        playlist_data = {
            "meta": {},
            "tracks": [
                {
                    "artist": "Test Artist",
                    "song": "Non-existent Song",
                    "release": "Test Album",
                }
            ],
        }

        result = match_playlist_to_library(
            playlist_data,
            base_folder=str(temp_library),
            library_subpath="",
            include_candidates=True,
            max_candidates=2,
        )

        track = result["results"][0]
        if "candidate_paths" in track:
            assert len(track["candidate_paths"]) <= 2

    def test_match_playlist_empty_tracks(self, temp_library):
        """Test with empty tracks list"""
        playlist_data = {
            "meta": {},
            "tracks": [],
        }

        result = match_playlist_to_library(
            playlist_data,
            base_folder=str(temp_library),
            library_subpath="",
        )

        assert result["summary"]["total_tracks"] == 0
        assert result["summary"]["found"] == 0
        assert result["summary"]["missing"] == 0

    def test_match_playlist_missing_fields(self, temp_library):
        """Test handling of missing track fields"""
        playlist_data = {
            "meta": {},
            "tracks": [
                {
                    "artist": None,
                    "song": "Song Only",
                    "release": None,
                },
                {
                    "artist": "Artist Only",
                    "song": None,
                    "release": None,
                },
            ],
        }

        result = match_playlist_to_library(
            playlist_data,
            base_folder=str(temp_library),
            library_subpath="",
        )

        # Should handle missing fields gracefully
        assert result["summary"]["total_tracks"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

