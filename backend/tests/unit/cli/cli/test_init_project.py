"""Unit tests for backend.cli.cli.init_project."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from backend.cli.cli.init_project import (
    TEMPLATE_BASIC_AGENT_YAML,
    TEMPLATE_ENV_EXAMPLE,
    TEMPLATE_README,
    init_project,
)


class TestInitProject(TestCase):
    """Test init_project function."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_default_name(self, mock_logger, mock_cwd):
        """Test initializing project with default name from directory."""
        mock_cwd.return_value = self.temp_path

        init_project()

        # Verify files were created
        self.assertTrue((self.temp_path / "agent.yaml").exists())
        self.assertTrue((self.temp_path / ".env.example").exists())
        self.assertTrue((self.temp_path / "README.md").exists())
        self.assertTrue((self.temp_path / "plugins").is_dir())
        self.assertTrue((self.temp_path / "plugins" / ".gitkeep").exists())

        # Verify logging
        mock_logger.info.assert_called()
        self.assertGreater(mock_logger.info.call_count, 0)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_custom_name(self, mock_logger, mock_cwd):
        """Test initializing project with custom name."""
        mock_cwd.return_value = self.temp_path

        init_project(name="my-custom-project")

        # Read agent.yaml and verify name
        with open(self.temp_path / "agent.yaml", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('name: "my-custom-project"', content)

        # Read README.md and verify name
        with open(self.temp_path / "README.md", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# my-custom-project", content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_creates_agent_yaml(self, mock_logger, mock_cwd):
        """Test that agent.yaml is created with correct structure."""
        mock_cwd.return_value = self.temp_path

        init_project(name="test-project")

        # Verify agent.yaml content
        with open(self.temp_path / "agent.yaml", "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('name: "test-project"', content)
        self.assertIn('description: "A Forge agent."', content)
        self.assertIn('version: "0.1.0"', content)
        self.assertIn('name: "CodeAct"', content)
        self.assertIn("max_steps: 30", content)
        self.assertIn('model: "gpt-4o"', content)
        self.assertIn("temperature: 0.0", content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_creates_env_example(self, mock_logger, mock_cwd):
        """Test that .env.example is created with correct content."""
        mock_cwd.return_value = self.temp_path

        init_project()

        # Verify .env.example content
        with open(self.temp_path / ".env.example", "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("OPENAI_API_KEY=sk-...", content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_creates_readme(self, mock_logger, mock_cwd):
        """Test that README.md is created with correct content."""
        mock_cwd.return_value = self.temp_path

        init_project(name="test-project")

        # Verify README.md content
        with open(self.temp_path / "README.md", "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("# test-project", content)
        self.assertIn("This is a Forge agent project.", content)
        self.assertIn("## Getting Started", content)
        self.assertIn("forge start", content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_creates_plugins_directory(self, mock_logger, mock_cwd):
        """Test that plugins directory is created."""
        mock_cwd.return_value = self.temp_path

        init_project()

        # Verify plugins directory exists
        plugins_dir = self.temp_path / "plugins"
        self.assertTrue(plugins_dir.is_dir())
        self.assertTrue((plugins_dir / ".gitkeep").exists())

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_skips_existing_agent_yaml(self, mock_logger, mock_cwd):
        """Test that existing agent.yaml is not overwritten."""
        mock_cwd.return_value = self.temp_path

        # Create existing agent.yaml with custom content
        existing_content = "# Existing content"
        with open(self.temp_path / "agent.yaml", "w", encoding="utf-8") as f:
            f.write(existing_content)

        init_project()

        # Verify existing content is preserved
        with open(self.temp_path / "agent.yaml", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, existing_content)

        # Verify warning was logged
        mock_logger.warning.assert_called()
        self.assertIn("already exists", mock_logger.warning.call_args[0][0])

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_skips_existing_env_example(self, mock_logger, mock_cwd):
        """Test that existing .env.example is not overwritten."""
        mock_cwd.return_value = self.temp_path

        # Create existing .env.example
        existing_content = "CUSTOM_VAR=value"
        with open(self.temp_path / ".env.example", "w", encoding="utf-8") as f:
            f.write(existing_content)

        init_project()

        # Verify existing content is preserved
        with open(self.temp_path / ".env.example", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, existing_content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_skips_existing_readme(self, mock_logger, mock_cwd):
        """Test that existing README.md is not overwritten."""
        mock_cwd.return_value = self.temp_path

        # Create existing README.md
        existing_content = "# Custom README"
        with open(self.temp_path / "README.md", "w", encoding="utf-8") as f:
            f.write(existing_content)

        init_project()

        # Verify existing content is preserved
        with open(self.temp_path / "README.md", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, existing_content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_plugins_directory_already_exists(self, mock_logger, mock_cwd):
        """Test that existing plugins directory is preserved."""
        mock_cwd.return_value = self.temp_path

        # Create existing plugins directory with content
        plugins_dir = self.temp_path / "plugins"
        plugins_dir.mkdir(exist_ok=True)
        (plugins_dir / "existing_plugin.py").touch()

        init_project()

        # Verify directory still exists with old and new content
        self.assertTrue(plugins_dir.is_dir())
        self.assertTrue((plugins_dir / "existing_plugin.py").exists())
        self.assertTrue((plugins_dir / ".gitkeep").exists())

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_logging_output(self, mock_logger, mock_cwd):
        """Test that appropriate logging messages are emitted."""
        mock_cwd.return_value = self.temp_path

        init_project(name="test-project")

        # Verify initialization log
        info_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        self.assertTrue(any("Initializing" in msg for msg in info_calls))

        # Verify file creation logs
        self.assertTrue(any("Created agent.yaml" in msg for msg in info_calls))
        self.assertTrue(any("Created .env.example" in msg for msg in info_calls))
        self.assertTrue(any("Created README.md" in msg for msg in info_calls))
        self.assertTrue(any("Created plugins/" in msg for msg in info_calls))

        # Verify success log
        self.assertTrue(any("initialized successfully" in msg for msg in info_calls))

        # Verify next steps log
        self.assertTrue(any("Next steps" in msg for msg in info_calls))

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_basic_template(self, mock_logger, mock_cwd):
        """Test initializing with basic template (default)."""
        mock_cwd.return_value = self.temp_path

        init_project(template="basic")

        # Verify files are created
        self.assertTrue((self.temp_path / "agent.yaml").exists())

    def test_template_basic_agent_yaml_structure(self):
        """Test that TEMPLATE_BASIC_AGENT_YAML has correct structure."""
        template = TEMPLATE_BASIC_AGENT_YAML
        self.assertIn('name: "{name}"', template)
        self.assertIn("agent:", template)
        self.assertIn("llm:", template)
        self.assertIn("config:", template)

    def test_template_env_example_structure(self):
        """Test that TEMPLATE_ENV_EXAMPLE has correct structure."""
        template = TEMPLATE_ENV_EXAMPLE
        self.assertIn("OPENAI_API_KEY=", template)

    def test_template_readme_structure(self):
        """Test that TEMPLATE_README has correct structure."""
        template = TEMPLATE_README
        self.assertIn("# {name}", template)
        self.assertIn("## Getting Started", template)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_name_with_special_characters(self, mock_logger, mock_cwd):
        """Test project initialization with special characters in name."""
        mock_cwd.return_value = self.temp_path

        init_project(name="my-project_123")

        # Verify name is used correctly in files
        with open(self.temp_path / "agent.yaml", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('name: "my-project_123"', content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_file_encoding(self, mock_logger, mock_cwd):
        """Test that files are created with UTF-8 encoding."""
        mock_cwd.return_value = self.temp_path

        init_project(name="test-project")

        # Verify files can be read with UTF-8
        with open(self.temp_path / "agent.yaml", "r", encoding="utf-8") as f:
            f.read()  # Should not raise encoding error
        with open(self.temp_path / ".env.example", "r", encoding="utf-8") as f:
            f.read()
        with open(self.temp_path / "README.md", "r", encoding="utf-8") as f:
            f.read()

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_empty_name(self, mock_logger, mock_cwd):
        """Test that empty string name falls back to directory name."""
        mock_cwd.return_value = self.temp_path

        init_project(name="")

        # Should use directory name
        with open(self.temp_path / "agent.yaml", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(f'name: "{self.temp_path.name}"', content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_none_name(self, mock_logger, mock_cwd):
        """Test that None name falls back to directory name."""
        mock_cwd.return_value = self.temp_path

        init_project(name=None)

        # Should use directory name
        with open(self.temp_path / "agent.yaml", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(f'name: "{self.temp_path.name}"', content)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_directory_name_fallback(self, mock_logger, mock_cwd):
        """Test that directory name is used when no name provided."""
        # Create temp directory with specific name
        temp_dir = Path(tempfile.mkdtemp(suffix="_forge_test"))
        mock_cwd.return_value = temp_dir

        try:
            init_project()

            # Verify directory name was used
            with open(temp_dir / "agent.yaml", "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn(f'name: "{temp_dir.name}"', content)
        finally:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("backend.cli.cli.init_project.Path.cwd")
    @patch("backend.cli.cli.init_project.logger")
    def test_init_project_all_files_created_together(self, mock_logger, mock_cwd):
        """Test that all files are created in a single init_project call."""
        mock_cwd.return_value = self.temp_path

        init_project(name="test-project")

        # Verify all files exist
        self.assertTrue((self.temp_path / "agent.yaml").exists())
        self.assertTrue((self.temp_path / ".env.example").exists())
        self.assertTrue((self.temp_path / "README.md").exists())
        self.assertTrue((self.temp_path / "plugins").is_dir())
        self.assertTrue((self.temp_path / "plugins" / ".gitkeep").exists())
