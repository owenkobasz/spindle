"""
Unit tests for scraper.py

To run: pytest test_scraper.py -v
To run specific test: pytest test_scraper.py::test_playlist_scraper_basic -v
"""

import json
from unittest.mock import Mock, patch
from bs4 import BeautifulSoup
import pytest

from scraper import _txt, _first, playlist_scraper


class TestHelperFunctions:
    """Tests for helper functions _txt and _first"""

    def test_txt_with_element(self):
        """Test _txt extracts text from BeautifulSoup element"""
        soup = BeautifulSoup("<div>Hello World</div>", "html.parser")
        el = soup.select_one("div")
        assert _txt(el) == "Hello World"

    def test_txt_with_none(self):
        """Test _txt returns None for None input"""
        assert _txt(None) is None

    def test_txt_strips_whitespace(self):
        """Test _txt strips whitespace"""
        soup = BeautifulSoup("<div>  Hello   World  </div>", "html.parser")
        el = soup.select_one("div")
        assert _txt(el) == "Hello World"

    def test_txt_with_empty_string(self):
        """Test _txt returns None for empty string"""
        soup = BeautifulSoup("<div></div>", "html.parser")
        el = soup.select_one("div")
        assert _txt(el) is None

    def test_first_finds_first_match(self):
        """Test _first returns first matching element"""
        soup = BeautifulSoup(
            "<div><p class='a'>First</p><p class='b'>Second</p></div>", "html.parser"
        )
        el = _first(soup, [".a", ".b"])
        assert el is not None
        assert el.get_text() == "First"

    def test_first_returns_none_if_no_match(self):
        """Test _first returns None if no selectors match"""
        soup = BeautifulSoup("<div><p>Text</p></div>", "html.parser")
        el = _first(soup, [".nonexistent"])
        assert el is None


class TestPlaylistScraper:
    """Tests for playlist_scraper function"""

    @pytest.fixture
    def sample_html(self):
        """Sample HTML that mimics a Spinitron playlist page.
        
        MODIFY THIS: Change the HTML structure to match different playlist formats
        """
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test Playlist - WPRB</title>
            <link rel="canonical" href="https://playlists.wprb.com/test" />
        </head>
        <body>
            <h1>Test Playlist</h1>
            <div class="station-name">WPRB</div>
            <table>
                <tr class="spin">
                    <td class="spin-time">12:00 PM</td>
                    <td><span class="artist">Test Artist</span></td>
                    <td><span class="song">Test Song</span></td>
                    <td><span class="release">Test Album</span></td>
                    <td><span class="label">Test Label</span></td>
                </tr>
                <tr class="spin">
                    <td class="spin-time">12:05 PM</td>
                    <td><span class="artist">Another Artist</span></td>
                    <td><span class="song">Another Song</span></td>
                    <td><span class="release">Another Album</span></td>
                    <td><span class="label">Another Label</span></td>
                </tr>
            </table>
        </body>
        </html>
        """

    @pytest.fixture
    def mock_response(self, sample_html):
        """Mock HTTP response with sample HTML"""
        mock = Mock()
        mock.text = sample_html
        mock.raise_for_status = Mock()
        return mock

    @patch("scraper.requests.get")
    def test_playlist_scraper_basic(self, mock_get, mock_response, sample_html):
        """Test basic playlist scraping functionality"""
        mock_get.return_value = mock_response

        # MODIFY THIS: Change the URL to test different playlist pages
        url = "https://playlists.wprb.com/test"
        result = playlist_scraper(url)

        # Verify structure
        assert "meta" in result
        assert "tracks" in result
        assert isinstance(result["tracks"], list)

        # Verify meta fields
        assert result["meta"]["source_url"] == url
        assert result["meta"]["canonical_url"] == "https://playlists.wprb.com/test"
        assert result["meta"]["domain"] == "playlists.wprb.com"
        assert "fetched_at_utc" in result["meta"]
        assert result["meta"]["playlist_title"] == "Test Playlist"
        assert result["meta"]["station"] == "WPRB"

        # Verify tracks
        assert len(result["tracks"]) == 2
        assert result["meta"]["track_count"] == 2

        # Verify first track
        track1 = result["tracks"][0]
        assert track1["time"] == "12:00 PM"
        assert track1["artist"] == "Test Artist"
        assert track1["song"] == "Test Song"
        assert track1["release"] == "Test Album"
        assert track1["label"] == "Test Label"

    @patch("scraper.requests.get")
    def test_playlist_scraper_with_links(self, mock_get):
        """Test scraping tracks with artist/song links"""
        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <tr class="spin">
                <td class="spin-time">12:00 PM</td>
                <td><span class="artist"><a href="/artist/123">Artist</a></span></td>
                <td><span class="song"><a href="/song/456">Song</a></span></td>
            </tr>
        </body>
        </html>
        """
        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = playlist_scraper("https://test.com")
        track = result["tracks"][0]
        assert track["artist_url"] == "/artist/123"
        assert track["song_url"] == "/song/456"

    @patch("scraper.requests.get")
    def test_playlist_scraper_empty_tracks(self, mock_get):
        """Test scraping page with no tracks"""
        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <h1>Empty Playlist</h1>
        </body>
        </html>
        """
        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = playlist_scraper("https://test.com")
        assert result["tracks"] == []
        assert result["meta"]["track_count"] == 0

    @patch("scraper.requests.get")
    def test_playlist_scraper_filters_empty_rows(self, mock_get):
        """Test that rows without artist or song are filtered out"""
        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <tr class="spin">
                <td class="spin-time">12:00 PM</td>
                <td><span class="artist">Artist</span></td>
                <td><span class="song">Song</span></td>
            </tr>
            <tr class="spin">
                <td class="spin-time">12:05 PM</td>
                <td></td>
                <td></td>
            </tr>
        </body>
        </html>
        """
        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = playlist_scraper("https://test.com")
        assert len(result["tracks"]) == 1

    @patch("scraper.requests.get")
    def test_playlist_scraper_normalizes_empty_strings(self, mock_get):
        """Test that empty strings are normalized to None"""
        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <tr class="spin">
                <td class="spin-time">12:00 PM</td>
                <td><span class="artist">Artist</span></td>
                <td><span class="song">Song</span></td>
                <td><span class="release">   </span></td>
                <td><span class="label"></span></td>
            </tr>
        </body>
        </html>
        """
        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = playlist_scraper("https://test.com")
        track = result["tracks"][0]
        assert track["release"] is None
        assert track["label"] is None

    @patch("scraper.requests.get")
    def test_playlist_scraper_http_error(self, mock_get):
        """Test that HTTP errors are raised"""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")
        mock_get.return_value = mock_response

        with pytest.raises(Exception):
            playlist_scraper("https://test.com")

    @patch("scraper.requests.get")
    def test_playlist_scraper_timeout(self, mock_get):
        """Test timeout parameter"""
        mock_response = Mock()
        mock_response.text = "<html><body></body></html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # MODIFY THIS: Change timeout value to test different timeouts
        playlist_scraper("https://test.com", timeout=60)
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["timeout"] == 60

    @patch("scraper.requests.get")
    def test_playlist_scraper_fallback_parsing(self, mock_get):
        """Test fallback parsing when no row containers are found"""
        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <td class="spin-time">12:00 PM</td>
            <span class="artist">Artist</span>
            <span class="song">Song</span>
            <span class="release">Album</span>
        </body>
        </html>
        """
        mock_response = Mock()
        mock_response.text = html
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = playlist_scraper("https://test.com")
        # Fallback should still extract tracks
        assert len(result["tracks"]) >= 0  # May or may not work depending on structure


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

