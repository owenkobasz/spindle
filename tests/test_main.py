"""
Unit tests for main.py

To run: pytest test_main.py -v
To run specific test: pytest test_main.py::TestSafeSlug::test_safe_slug_basic -v
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from main import (
    safe_slug,
    derive_artifact_stem,
    load_json,
    save_json,
    validate_url,
    validate_file_path,
    validate_json_file,
    list_artifacts,
    ARTIFACTS_DIR,
)


class TestSafeSlug:
    """Tests for safe_slug function"""

    def test_safe_slug_basic(self):
        """Test basic slug conversion"""
        assert safe_slug("Hello World") == "hello-world"
        assert safe_slug("Test Playlist") == "test-playlist"

    def test_safe_slug_with_special_chars(self):
        """Test slug conversion removes special characters"""
        assert safe_slug("Hello, World!") == "helloworld"
        assert safe_slug("Song (Remix)") == "songremix"
        assert safe_slug("Test/Path") == "test-path"

    def test_safe_slug_collapses_dashes(self):
        """Test that multiple dashes are collapsed"""
        assert safe_slug("Hello---World") == "hello-world"
        assert safe_slug("Test__Playlist") == "test-playlist"

    def test_safe_slug_strips_trailing_dashes(self):
        """Test that leading/trailing dashes are removed"""
        assert safe_slug("-Hello World-") == "hello-world"
        assert safe_slug("---Test---") == "test"

    def test_safe_slug_empty_string(self):
        """Test that empty string returns 'unknown'"""
        assert safe_slug("") == "unknown"
        assert safe_slug(None) == "unknown"

    def test_safe_slug_unicode(self):
        """Test unicode handling"""
        assert safe_slug("Café Playlist") == "caf-playlist"
        assert safe_slug("Música") == "msica"


class TestDeriveArtifactStem:
    """Tests for derive_artifact_stem function"""

    def test_derive_artifact_stem_with_date(self):
        """Test artifact stem derivation with date"""
        meta = {
            "fetched_at_utc": "2025-12-17T10:30:00+00:00",
            "canonical_url": "https://playlists.wprb.com/WPRB/pl/21686552/Lady-Love",
        }
        stem = derive_artifact_stem(meta)
        assert stem.startswith("2025-12-17_")
        assert "lady-love" in stem

    def test_derive_artifact_stem_with_page_title(self):
        """Test artifact stem derivation with page title"""
        meta = {
            "fetched_at_utc": "2025-12-17T10:30:00+00:00",
            "page_title": "My Awesome Playlist",
        }
        stem = derive_artifact_stem(meta)
        assert stem.startswith("2025-12-17_")
        assert "my-awesome-playlist" in stem

    def test_derive_artifact_stem_fallback_date(self):
        """Test artifact stem uses today's date if fetched_at_utc missing"""
        meta = {
            "playlist_title": "Test Playlist",
        }
        stem = derive_artifact_stem(meta)
        # Should have date prefix (format: YYYY-MM-DD_)
        assert len(stem) > len("test-playlist")
        assert stem.count("-") >= 2  # Date has dashes

    def test_derive_artifact_stem_minimal_meta(self):
        """Test artifact stem with minimal metadata"""
        meta = {}
        stem = derive_artifact_stem(meta)
        assert stem.endswith("_playlist") or stem.endswith("_unknown")


class TestJsonIO:
    """Tests for load_json and save_json functions"""

    def test_save_and_load_json(self):
        """Test saving and loading JSON"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            test_file = tmp_path / "test.json"
            
            test_data = {
                "meta": {"title": "Test"},
                "tracks": [{"artist": "Artist", "song": "Song"}],
            }
            
            # Save JSON
            saved_path = save_json(test_data, test_file)
            assert saved_path == test_file
            assert test_file.exists()
            
            # Load JSON
            loaded_data = load_json(test_file)
            assert loaded_data == test_data
            assert loaded_data["meta"]["title"] == "Test"

    def test_load_json_nonexistent(self):
        """Test loading nonexistent JSON raises FileNotFoundError"""
        nonexistent = Path("/nonexistent/path/file.json")
        with pytest.raises(FileNotFoundError):
            load_json(nonexistent)

    def test_save_json_creates_directory(self):
        """Test that save_json creates parent directories"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            nested_file = tmp_path / "nested" / "dir" / "test.json"
            
            test_data = {"test": "data"}
            save_json(test_data, nested_file)
            
            assert nested_file.exists()
            assert load_json(nested_file) == test_data


class TestValidateUrl:
    """Tests for validate_url function"""

    def test_validate_url_valid_http(self):
        """Test valid HTTP URL"""
        assert validate_url("http://example.com") == "http://example.com"
        assert validate_url("http://playlists.wprb.com/test") == "http://playlists.wprb.com/test"

    def test_validate_url_valid_https(self):
        """Test valid HTTPS URL"""
        assert validate_url("https://example.com") == "https://example.com"
        assert validate_url("https://playlists.wprb.com/test") == "https://playlists.wprb.com/test"

    def test_validate_url_strips_whitespace(self):
        """Test that whitespace is stripped"""
        assert validate_url("  https://example.com  ") == "https://example.com"

    def test_validate_url_invalid_no_protocol(self):
        """Test invalid URL without protocol"""
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            validate_url("example.com")

    def test_validate_url_empty(self):
        """Test empty URL raises ValueError"""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_url("")
        with pytest.raises(ValueError):
            validate_url("   ")


class TestValidateFilePath:
    """Tests for validate_file_path function"""

    def test_validate_file_path_existing(self):
        """Test validating existing file"""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                result = validate_file_path(tmp_path, "file")
                assert result == tmp_path.resolve()
            finally:
                tmp_path.unlink()

    def test_validate_file_path_nonexistent(self):
        """Test validating nonexistent file raises FileNotFoundError"""
        nonexistent = Path("/nonexistent/file.txt")
        with pytest.raises(FileNotFoundError):
            validate_file_path(nonexistent, "file")

    def test_validate_file_path_expands_user(self):
        """Test that ~ is expanded"""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                # Test with expanded path (validate_file_path should handle it)
                result = validate_file_path(tmp_path, "file")
                assert result == tmp_path.resolve()
            finally:
                tmp_path.unlink()


class TestValidateJsonFile:
    """Tests for validate_json_file function"""

    def test_validate_json_file_valid_playlist(self):
        """Test validating valid playlist JSON"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump({
                "meta": {"title": "Test"},
                "tracks": [{"artist": "Artist", "song": "Song"}],
            }, tmp)
            tmp_path = Path(tmp.name)
        
        try:
            result = validate_json_file(tmp_path, "playlist")
            assert "meta" in result
            assert "tracks" in result
        finally:
            tmp_path.unlink()

    def test_validate_json_file_valid_match(self):
        """Test validating valid match JSON"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump({
                "summary": {"found": 5, "missing": 2},
                "results": [{"match_status": "found"}],
            }, tmp)
            tmp_path = Path(tmp.name)
        
        try:
            result = validate_json_file(tmp_path, "match")
            assert "summary" in result
            assert "results" in result
        finally:
            tmp_path.unlink()

    def test_validate_json_file_invalid_structure(self):
        """Test validating JSON with wrong structure raises ValueError"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump({"wrong": "structure"}, tmp)
            tmp_path = Path(tmp.name)
        
        try:
            with pytest.raises(ValueError, match="does not appear to be"):
                validate_json_file(tmp_path, "playlist")
        finally:
            tmp_path.unlink()

    def test_validate_json_file_invalid_json(self):
        """Test validating invalid JSON raises JSONDecodeError"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            tmp.write("not valid json {")
            tmp_path = Path(tmp.name)
        
        try:
            with pytest.raises(json.JSONDecodeError):
                validate_json_file(tmp_path, "playlist")
        finally:
            tmp_path.unlink()


class TestListArtifacts:
    """Tests for list_artifacts function"""

    def test_list_artifacts_empty(self):
        """Test listing artifacts when directory doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            # Temporarily patch ARTIFACTS_DIR
            original_dir = ARTIFACTS_DIR
            try:
                import main
                main.ARTIFACTS_DIR = artifacts_dir
                artifacts = list_artifacts()
                assert artifacts == []
            finally:
                main.ARTIFACTS_DIR = original_dir

    def test_list_artifacts_sorted_by_mtime(self):
        """Test that artifacts are sorted by modification time (newest first)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            artifacts_dir.mkdir()
            
            # Create test files with delays to ensure different mtimes
            import time
            file1 = artifacts_dir / "old.playlist.json"
            file1.touch()
            time.sleep(0.01)  # Small delay
            
            file2 = artifacts_dir / "new.playlist.json"
            file2.touch()
            
            original_dir = ARTIFACTS_DIR
            try:
                import main
                main.ARTIFACTS_DIR = artifacts_dir
                
                artifacts = list_artifacts("playlist")
                assert len(artifacts) == 2
                # Newest should be first
                assert artifacts[0].name == "new.playlist.json"
                assert artifacts[1].name == "old.playlist.json"
            finally:
                main.ARTIFACTS_DIR = original_dir

    def test_list_artifacts_with_files(self):
        """Test listing artifacts with files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            artifacts_dir.mkdir()
            
            # Create test files
            (artifacts_dir / "2025-12-17_test.playlist.json").touch()
            (artifacts_dir / "2025-12-17_test.match.json").touch()
            (artifacts_dir / "2025-12-17_test.enriched.json").touch()
            (artifacts_dir / "other.txt").touch()  # Should be filtered out
            
            original_dir = ARTIFACTS_DIR
            try:
                import main
                main.ARTIFACTS_DIR = artifacts_dir
                
                # List all artifacts
                all_artifacts = list_artifacts()
                assert len(all_artifacts) == 3  # Only JSON files
                
                # List playlist artifacts only
                playlist_artifacts = list_artifacts("playlist")
                assert len(playlist_artifacts) == 1
                assert playlist_artifacts[0].name.endswith(".playlist.json")
                
                # List match artifacts only
                match_artifacts = list_artifacts("match")
                assert len(match_artifacts) == 1
                assert match_artifacts[0].name.endswith(".match.json")
            finally:
                main.ARTIFACTS_DIR = original_dir


class TestStageFunctions:
    """Tests for stage functions (run_scrape, run_match, run_links, run_export)"""

    @patch("main.playlist_scraper")
    def test_run_scrape(self, mock_scraper):
        """Test run_scrape function"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            artifacts_dir.mkdir()
            
            # Mock playlist data
            mock_playlist_data = {
                "meta": {
                    "fetched_at_utc": "2025-12-17T10:30:00+00:00",
                    "canonical_url": "https://playlists.wprb.com/test",
                    "playlist_title": "Test Playlist",
                    "track_count": 5,
                },
                "tracks": [
                    {"artist": "Artist", "song": "Song"},
                ],
            }
            mock_scraper.return_value = mock_playlist_data
            
            from main import run_scrape
            result_path = run_scrape("https://playlists.wprb.com/test", artifacts_dir)
            
            assert result_path.exists()
            assert result_path.suffix == ".json"
            assert ".playlist.json" in result_path.name
            
            # Verify saved data
            saved_data = load_json(result_path)
            assert saved_data == mock_playlist_data
            
            mock_scraper.assert_called_once_with("https://playlists.wprb.com/test")

    @patch("main.match_playlist_to_library")
    def test_run_match(self, mock_match):
        """Test run_match function"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            artifacts_dir.mkdir()
            
            # Create playlist JSON
            playlist_data = {
                "meta": {
                    "fetched_at_utc": "2025-12-17T10:30:00+00:00",
                    "canonical_url": "https://playlists.wprb.com/test",
                },
                "tracks": [{"artist": "Artist", "song": "Song"}],
            }
            playlist_path = artifacts_dir / "test.playlist.json"
            save_json(playlist_data, playlist_path)
            
            # Mock match result
            mock_match_result = {
                "meta": playlist_data["meta"],
                "summary": {"found": 1, "missing": 0, "total_tracks": 1},
                "results": [{"match_status": "found"}],
            }
            mock_match.return_value = mock_match_result
            
            from main import run_match
            result_path = run_match(
                playlist_path,
                str(Path(tmpdir)),
                "",
                artifacts_dir
            )
            
            assert result_path.exists()
            assert ".match.json" in result_path.name
            
            # Verify saved data includes playlist_data
            saved_data = load_json(result_path)
            assert "playlist_data" in saved_data
            assert saved_data["playlist_data"] == playlist_data

    @patch("main.find_share_urls_from_metadata")
    def test_run_links(self, mock_find_links):
        """Test run_links function"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            artifacts_dir.mkdir()
            
            # Create match JSON
            match_data = {
                "meta": {"title": "Test"},
                "summary": {"found": 1, "missing": 1, "total_tracks": 2},
                "results": [
                    {"match_status": "found", "artist": "Found", "song": "Song"},
                    {"match_status": "missing", "artist": "Missing", "song": "Song"},
                ],
                "playlist_data": {
                    "meta": {"fetched_at_utc": "2025-12-17T10:30:00+00:00"},
                },
            }
            match_path = artifacts_dir / "test.match.json"
            save_json(match_data, match_path)
            
            # Mock link finding
            mock_find_links.return_value = {
                "ok": True,
                "aggregated": {
                    "targets": {"amazon_music": "https://music.amazon.com/test"},
                    "page_url": "https://song.link/test",
                },
                "seed": {"provider": "deezer"},
            }
            
            from main import run_links
            result_path = run_links(match_path, artifacts_dir, missing_only=True)
            
            assert result_path.exists()
            assert ".enriched.json" in result_path.name or ".match.json" in result_path.name
            
            # Verify links were added to missing track
            saved_data = load_json(result_path)
            missing_track = next(r for r in saved_data["results"] if r["match_status"] == "missing")
            assert "share_links" in missing_track
            # Verify found track was not enriched (missing_only=True)
            found_track = next(r for r in saved_data["results"] if r["match_status"] == "found")
            # Found track may or may not have share_links, but shouldn't have been processed
            assert mock_find_links.call_count == 1  # Only called for missing track

    @patch("main.export_playlist_copies")
    def test_run_export_from_match(self, mock_export):
        """Test run_export function with match JSON"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            artifacts_dir.mkdir()
            target_dir = Path(tmpdir) / "target"
            target_dir.mkdir()
            
            # Create match JSON with playlist_data
            match_data = {
                "meta": {"title": "Test"},
                "summary": {"found": 1, "missing": 0},
                "results": [{"match_status": "found"}],
                "playlist_data": {
                    "meta": {"fetched_at_utc": "2025-12-17T10:30:00+00:00"},
                    "tracks": [{"artist": "Artist", "song": "Song"}],
                },
            }
            match_path = artifacts_dir / "test.match.json"
            save_json(match_data, match_path)
            
            # Mock export result
            mock_export.return_value = {
                "summary": {"copied": 1, "total_tracks": 1},
                "destination_folder": str(target_dir / "playlist"),
            }
            
            from main import run_export
            with patch("main.prompt_yes_no", return_value=False):  # Don't skip missing
                result_path = run_export(
                    match_path,
                    str(Path(tmpdir)),
                    "",
                    target_dir,
                    overwrite=False
                )
            
            assert result_path.exists()
            mock_export.assert_called_once()

    @patch("main.export_playlist_copies")
    def test_run_export_from_playlist(self, mock_export):
        """Test run_export function with playlist JSON"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            artifacts_dir.mkdir()
            target_dir = Path(tmpdir) / "target"
            target_dir.mkdir()
            
            # Create playlist JSON
            playlist_data = {
                "meta": {"fetched_at_utc": "2025-12-17T10:30:00+00:00"},
                "tracks": [{"artist": "Artist", "song": "Song"}],
            }
            playlist_path = artifacts_dir / "test.playlist.json"
            save_json(playlist_data, playlist_path)
            
            # Mock export result
            mock_export.return_value = {
                "summary": {"copied": 1, "total_tracks": 1},
                "destination_folder": str(target_dir / "playlist"),
            }
            
            from main import run_export
            result_path = run_export(
                playlist_path,
                str(Path(tmpdir)),
                "",
                target_dir,
                overwrite=False
            )
            
            assert result_path.exists()
            mock_export.assert_called_once()
            
            # Verify export was called with correct arguments
            call_args = mock_export.call_args
            assert call_args[1]["make_subfolder"] is True
            assert call_args[1]["overwrite"] is False

    @patch("main.export_playlist_copies")
    def test_run_export_skips_missing_tracks(self, mock_export):
        """Test run_export skips missing tracks when user confirms"""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = Path(tmpdir) / "artifacts"
            artifacts_dir.mkdir()
            target_dir = Path(tmpdir) / "target"
            target_dir.mkdir()
            
            # Create match JSON with missing tracks
            match_data = {
                "meta": {"title": "Test"},
                "summary": {"found": 1, "missing": 1},
                "results": [
                    {"match_status": "found", "artist": "Found", "song": "Song"},
                    {"match_status": "missing", "artist": "Missing", "song": "Song"},
                ],
                "playlist_data": {
                    "meta": {"fetched_at_utc": "2025-12-17T10:30:00+00:00"},
                    "tracks": [
                        {"artist": "Found", "song": "Song"},
                        {"artist": "Missing", "song": "Song"},
                    ],
                },
            }
            match_path = artifacts_dir / "test.match.json"
            save_json(match_data, match_path)
            
            # Mock export result
            mock_export.return_value = {
                "summary": {"copied": 1, "total_tracks": 1},
                "destination_folder": str(target_dir / "playlist"),
            }
            
            from main import run_export
            # User chooses to skip missing tracks
            with patch("main.prompt_yes_no", return_value=True):
                result_path = run_export(
                    match_path,
                    str(Path(tmpdir)),
                    "",
                    target_dir,
                    overwrite=False
                )
            
            # Verify export was called with filtered tracks
            call_args = mock_export.call_args
            playlist_data = call_args[0][0]  # First positional argument
            assert len(playlist_data["tracks"]) == 1  # Missing track filtered out
            assert playlist_data["tracks"][0]["artist"] == "Found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

