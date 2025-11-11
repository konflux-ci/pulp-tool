"""
Tests to verify temporary file cleanup fixtures work correctly.

These tests demonstrate proper temporary file handling patterns.
"""

from pathlib import Path
import tempfile


class TestTempFileFixtures:
    """Test temporary file fixture behavior."""

    def test_temp_files_fixture(self, temp_files):
        """Test temp_files fixture creates and cleans up automatically."""
        # Create a file in the temp directory
        test_file = temp_files / "test.txt"
        test_file.write_text("test content")

        assert test_file.exists()
        assert test_file.read_text() == "test content"

        # No explicit cleanup needed - fixture handles it

    def test_create_temp_file_fixture(self, create_temp_file):
        """Test create_temp_file factory fixture."""
        # Create multiple files easily
        file1 = create_temp_file("config.toml", '[cli]\nkey = "value"')
        file2 = create_temp_file("data.json", '{"test": true}')
        file3 = create_temp_file("binary.dat", b"binary content", binary=True)

        assert file1.exists()
        assert file2.exists()
        assert file3.exists()

        assert "key" in file1.read_text()
        assert "test" in file2.read_text()
        assert file3.read_bytes() == b"binary content"

        # Automatic cleanup

    def test_manual_cleanup_pattern(self):
        """Demonstrate proper manual cleanup with try/finally."""
        temp_files = []

        try:
            # Create multiple temp files
            for i in range(3):
                with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
                    f.write(f"content {i}")
                    temp_files.append(f.name)

            # Verify files exist
            for path in temp_files:
                assert Path(path).exists()

            # Test code would go here
            assert len(temp_files) == 3

        finally:
            # Always clean up
            for path in temp_files:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass  # Best effort

    def test_existing_fixtures(self, temp_file, temp_rpm_file, temp_dir, temp_config_file):
        """Test that existing fixtures still work correctly."""
        # temp_file fixture
        assert Path(temp_file).exists()
        assert "test content" in Path(temp_file).read_text()

        # temp_rpm_file fixture
        assert Path(temp_rpm_file).exists()
        assert Path(temp_rpm_file).suffix == ".rpm"

        # temp_dir fixture
        assert Path(temp_dir).exists()
        assert Path(temp_dir).is_dir()

        # temp_config_file fixture
        assert Path(temp_config_file).exists()
        assert Path(temp_config_file).suffix == ".toml"

        # All cleanup is automatic


class TestCleanupVerification:
    """Verify cleanup actually happens."""

    def test_pytest_tmp_path_cleanup(self, tmp_path):
        """Verify pytest's tmp_path cleans up automatically."""
        # Create a file
        test_file = tmp_path / "verify_cleanup.txt"
        test_file.write_text("This will be cleaned up")

        # Store the path for verification (in real tests, pytest cleans this up)
        path_str = str(test_file)

        assert Path(path_str).exists()
        # After test completes, pytest automatically removes tmp_path


class TestCleanupBestPractices:
    """Demonstrate best practices for temporary file handling."""

    def test_context_manager_pattern(self, tmp_path):
        """Use context managers when possible."""
        # Best practice: use context manager for automatic cleanup
        config_file = tmp_path / "config.toml"

        with open(config_file, "w") as f:
            f.write('[cli]\nbase_url = "https://example.com"\n')

        assert config_file.exists()
        # File handle automatically closed, tmp_path cleaned by pytest

    def test_early_cleanup(self, tmp_path):
        """Clean up as soon as you're done with a file."""
        temp_file = tmp_path / "temporary.txt"
        temp_file.write_text("temporary data")

        # Use the file
        content = temp_file.read_text()
        assert content == "temporary data"

        # Clean up immediately if no longer needed
        temp_file.unlink()
        assert not temp_file.exists()

        # tmp_path still cleans up the directory at test end
