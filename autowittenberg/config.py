"""Reads settings and secrets from environment variables.

Locally they come from the .env file; on GitHub Actions they come from repository secrets.
"""
import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

# macOS's built-in Python triggers a harmless SSL-library warning; hide it.
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

load_dotenv()


def require(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing setting: {name}. Add it to your .env file (locally) "
            f"or as a GitHub Actions secret."
        )
    return value


def optional(name, default=""):
    return os.environ.get(name, default).strip()


def save_to_env_file(name, value, env_path=None):
    """Sets NAME=value in the local .env file (replacing an existing line or appending)."""
    env_path = Path(env_path) if env_path else Path(__file__).parent.parent / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    for i, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    env_path.write_text("\n".join(lines) + "\n")
    os.environ[name] = value
