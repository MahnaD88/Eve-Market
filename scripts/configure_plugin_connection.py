"""Bind the package to a real, owner-created ChatGPT MCP connection."""
import argparse
import json
import re
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "eve-industry"


def configure(app_id, plugin_root=DEFAULT_ROOT):
    if not re.fullmatch(r"asdk_app_(?!v_)[A-Za-z0-9][A-Za-z0-9_-]*", app_id):
        raise ValueError("Use the underlying asdk_app_... app ID, not a plugin_ ID or version ID")
    plugin_root = Path(plugin_root).resolve()
    path = plugin_root / ".codex-plugin" / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("name") != "eve-industry":
        raise ValueError("Expected the eve-industry plugin")
    mapping = {"apps": {"eve-industry": {"id": app_id, "required": True}}}
    manifest["apps"] = "./.app.json"
    manifest.pop("mcpServers", None)
    # Disable default MCP auto-discovery as well as the manifest reference.
    # Preserve the reviewed local config under a non-default filename.
    local = plugin_root / ".mcp.json"
    backup = plugin_root / ".mcp.local.json"
    if local.exists():
        if backup.exists():
            raise ValueError("Local MCP backup already exists; review connection files before rebinding")
        expected = [
            {"mcpServers": {"eve-industry": {"type": "http", "url": url}}}
            for url in ("http://127.0.0.1:8000/mcp", "https://project-jm8k1.vercel.app/mcp")
        ]
        if json.loads(local.read_text(encoding="utf-8")) not in expected:
            raise ValueError("Local MCP config was customised; review it before rebinding")
        local.rename(backup)
    (plugin_root / ".app.json").write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--plugin-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    configure(args.app_id, args.plugin_root)
    print("Registered app binding written. Package installation is a separate step; this does not install or publish the plugin.")
