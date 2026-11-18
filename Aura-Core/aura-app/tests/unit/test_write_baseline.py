"""Unit tests for the write_baseline helper (BF-03)."""

import json
import os
from pathlib import Path

import pytest

from tests.conftest import write_baseline


class TestWriteBaseline:
    """Tests for the write_baseline helper function."""

    def test_write_baseline_skips_when_env_unset(self, tmp_path, monkeypatch):
        """When RECORD_BASELINE is not set, the file should not be written."""
        # Ensure RECORD_BASELINE is not set
        monkeypatch.delenv("RECORD_BASELINE", raising=False)
        
        test_file = tmp_path / "test_baseline.json"
        test_data = {"key": "value", "number": 42}
        
        # Call write_baseline
        result = write_baseline(test_file, test_data)
        
        # Should return False (not written)
        assert result is False
        
        # File should not exist
        assert not test_file.exists()

    def test_write_baseline_skips_when_env_empty(self, tmp_path, monkeypatch):
        """When RECORD_BASELINE is empty string, the file should not be written."""
        monkeypatch.setenv("RECORD_BASELINE", "")
        
        test_file = tmp_path / "test_baseline.json"
        test_data = {"key": "value"}
        
        result = write_baseline(test_file, test_data)
        
        assert result is False
        assert not test_file.exists()

    def test_write_baseline_skips_when_env_not_one(self, tmp_path, monkeypatch):
        """When RECORD_BASELINE is set to something other than '1', the file should not be written."""
        monkeypatch.setenv("RECORD_BASELINE", "0")
        
        test_file = tmp_path / "test_baseline.json"
        test_data = {"key": "value"}
        
        result = write_baseline(test_file, test_data)
        
        assert result is False
        assert not test_file.exists()

    def test_write_baseline_writes_when_env_is_one(self, tmp_path, monkeypatch):
        """When RECORD_BASELINE equals '1', the file should be written with correct content."""
        monkeypatch.setenv("RECORD_BASELINE", "1")
        
        test_file = tmp_path / "test_baseline.json"
        test_data = {"key": "value", "number": 42, "nested": {"a": 1}}
        
        result = write_baseline(test_file, test_data)
        
        # Should return True (written)
        assert result is True
        
        # File should exist
        assert test_file.exists()
        
        # Content should match
        written_data = json.loads(test_file.read_text())
        assert written_data == test_data

    def test_write_baseline_creates_parent_directories(self, tmp_path, monkeypatch):
        """write_baseline should create parent directories when needed."""
        monkeypatch.setenv("RECORD_BASELINE", "1")
        
        test_file = tmp_path / "subdir" / "nested" / "test_baseline.json"
        test_data = {"key": "value"}
        
        result = write_baseline(test_file, test_data)
        
        assert result is True
        assert test_file.exists()
        written_data = json.loads(test_file.read_text())
        assert written_data == test_data

    def test_write_baseline_does_not_modify_existing_file_when_env_unset(self, tmp_path, monkeypatch):
        """When RECORD_BASELINE is not set, existing file content and mtime should be unchanged."""
        monkeypatch.delenv("RECORD_BASELINE", raising=False)
        
        test_file = tmp_path / "test_baseline.json"
        original_data = {"original": "data"}
        test_file.write_text(json.dumps(original_data, indent=2))
        
        # Get original mtime
        original_mtime = test_file.stat().st_mtime
        
        # Try to write new data
        new_data = {"new": "data"}
        result = write_baseline(test_file, new_data)
        
        # Should not write
        assert result is False
        
        # Content should be unchanged
        written_data = json.loads(test_file.read_text())
        assert written_data == original_data
        
        # mtime should be unchanged (or at least not changed by our write)
        new_mtime = test_file.stat().st_mtime
        assert new_mtime == original_mtime

    def test_emotion_baseline_record_does_not_write_when_env_unset(self, tmp_path, monkeypatch):
        """Test that the emotion baseline recording test doesn't write when RECORD_BASELINE is unset."""
        # This test verifies the actual recording test behavior
        monkeypatch.delenv("RECORD_BASELINE", raising=False)
        
        # We'll use the actual output path
        output_path = Path("docs/metrics/emotion_before.json")
        
        # Get original mtime if file exists
        original_mtime = None
        if output_path.exists():
            original_mtime = output_path.stat().st_mtime
            original_content = output_path.read_text()
        else:
            original_content = None
        
        # Run the actual test function logic (copying the test to use a temp path)
        # We can't easily call the test function directly, so we verify the helper behavior
        # with the same path pattern
        test_output = {"test": "data"}
        result = write_baseline(output_path, test_output)
        
        assert result is False
        
        # If file existed before, it should be unchanged
        if original_content is not None:
            assert output_path.read_text() == original_content
            assert output_path.stat().st_mtime == original_mtime
        else:
            # File should not have been created
            assert not output_path.exists()

    def test_memory_baseline_record_does_not_write_when_env_unset(self, tmp_path, monkeypatch):
        """Test that the memory baseline recording test doesn't write when RECORD_BASELINE is unset."""
        monkeypatch.delenv("RECORD_BASELINE", raising=False)
        
        output_path = Path("docs/metrics/memory_before.json")
        
        original_mtime = None
        if output_path.exists():
            original_mtime = output_path.stat().st_mtime
            original_content = output_path.read_text()
        else:
            original_content = None
        
        test_output = {"test": "data"}
        result = write_baseline(output_path, test_output)
        
        assert result is False
        
        if original_content is not None:
            assert output_path.read_text() == original_content
            assert output_path.stat().st_mtime == original_mtime
        else:
            assert not output_path.exists()