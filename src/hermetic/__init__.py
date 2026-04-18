"""Sync Claude Code plugins into Hermes as native skills and delegation skills."""

from .core import sync_plugin
from .manifest import load_manifest, save_manifest

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "sync_plugin",
    "load_manifest",
    "save_manifest",
]
