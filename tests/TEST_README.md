# Unit Tests

This directory contains unit tests for `scraper.py` and `match_playlist_to_library.py`.

## Setup

Install the required testing dependency:

```bash
pip install pytest
```

Or install all dependencies (if you have a requirements file):

```bash
pip install -r requirements.txt
```

## Running Tests

### Run all tests:
```bash
pytest test_scraper.py test_match_playlist_to_library.py -v
```

### Run tests for a specific file:
```bash
pytest test_scraper.py -v
pytest test_match_playlist_to_library.py -v
```

### Run a specific test:
```bash
pytest test_scraper.py::TestHelperFunctions::test_txt_with_element -v
pytest test_match_playlist_to_library.py::TestNormFunction::test_norm_basic -v
```

### Run with coverage:
```bash
pytest --cov=. --cov-report=html test_scraper.py test_match_playlist_to_library.py
```

## Test Structure

### `test_scraper.py`
Tests for the playlist scraper functionality:
- Helper functions (`_txt`, `_first`)
- Main `playlist_scraper` function with mocked HTTP responses
- Edge cases (empty tracks, HTTP errors, etc.)

### `test_match_playlist_to_library.py`
Tests for the library matching functionality:
- String normalization (`_norm`)
- Audio file iteration
- Index building
- Main `match_playlist_to_library` function with temporary directories

## Modifying Tests

The tests are designed to be easy to modify:

1. **Test Data**: Look for `@pytest.fixture` functions - these contain sample data you can modify
2. **Test Cases**: Each test function is clearly named and focused on one behavior
3. **Comments**: Look for `MODIFY THIS:` comments that indicate where you can customize tests

### Example: Adding a new test case

```python
def test_norm_your_custom_case(self):
    """Test your specific normalization case"""
    # MODIFY THIS: Add your test case
    assert _norm("Your Input") == "expected output"
```

### Example: Modifying test data

In the fixture:
```python
@pytest.fixture
def sample_playlist_data(self):
    """Sample playlist data structure.
    
    MODIFY THIS: Change the playlist data to match your test cases
    """
    return {
        "meta": {...},
        "tracks": [...],  # Add your tracks here
    }
```

## Notes

- Tests use temporary directories for file system operations (automatically cleaned up)
- HTTP requests are mocked to avoid network calls during testing
- Tests are isolated and can be run in any order

