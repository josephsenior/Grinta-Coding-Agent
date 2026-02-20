"""Initialize a new Forge agent project."""

from pathlib import Path

from backend.core.logger import forge_logger as logger

TEMPLATE_BASIC_AGENT_YAML = """
name: "{name}"
description: "A Forge agent."
version: "0.1.0"

agent:
  name: "CodeAct"
  config:
    max_steps: 30

llm:
  model: "gpt-4o"
  temperature: 0.0
"""

TEMPLATE_ENV_EXAMPLE = """
OPENAI_API_KEY=sk-...
"""

TEMPLATE_README = """
# {name}

This is a Forge agent project.

## Getting Started

1. Copy `.env.example` to `.env` and fill in your API keys.
2. Run `forge start` to launch the agent.
"""


def init_project(name: str | None = None, template: str = "basic") -> None:
    """Initialize a new Forge project in the current directory.

    Args:
        name: Name of the project (defaults to current directory name)
        template: Template to use (currently only 'basic' supported)
    """
    cwd = Path.cwd()
    project_name = name or cwd.name

    logger.info("Initializing Forge project '%s' in %s...", project_name, cwd)

    # Create agent.yaml
    agent_yaml_path = cwd / "agent.yaml"
    if not agent_yaml_path.exists():
        with open(agent_yaml_path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE_BASIC_AGENT_YAML.format(name=project_name))
        logger.info("Created agent.yaml")
    else:
        logger.warning("agent.yaml already exists, skipping")

    # Create .env.example
    env_example_path = cwd / ".env.example"
    if not env_example_path.exists():
        with open(env_example_path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE_ENV_EXAMPLE)
        logger.info("Created .env.example")

    # Create README.md
    readme_path = cwd / "README.md"
    if not readme_path.exists():
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE_README.format(name=project_name))
        logger.info("Created README.md")

    # Create plugins directory
    plugins_dir = cwd / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    (plugins_dir / ".gitkeep").touch(exist_ok=True)
    logger.info("Created plugins/ directory")

    logger.info("Project '%s' initialized successfully!", project_name)
    logger.info("Next steps:")
    logger.info("  1. cp .env.example .env")
    logger.info("  2. forge serve")
