"""Create a standalone Vercel deployment folder without the existing backend or database.
This prepares files only. It never creates a project or invokes Vercel.
"""
import argparse
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def prepare(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new, empty destination path; existing folders are never overwritten")
    # Do not recurse into an output nested within the source adapter.
    if destination.is_relative_to(REPO / "mcp_adapter"):
        raise ValueError("Destination cannot be inside mcp_adapter")
    destination.mkdir(parents=True)
    shutil.copytree(REPO / "mcp_adapter", destination / "mcp_adapter",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (destination / "app.py").write_text("from mcp_adapter.asgi import app\n", encoding="utf-8")
    (destination / "requirements.txt").write_text("-r mcp_adapter/requirements.txt\n", encoding="utf-8")
    (destination / ".python-version").write_text("3.14\n", encoding="utf-8")
    (destination / "vercel.json").write_text(json.dumps({
        "functions": {"app.py": {"maxDuration": 180}}
    }, indent=2) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(prepare(args.destination))
