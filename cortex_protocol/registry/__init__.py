"""Cortex Protocol -- Versioned Agent Registry.

Local file-based registry for publishing, versioning, and discovering
agent specs. Stores specs at ~/.cortex-protocol/registry/.
"""

from .local import LocalRegistry
from .resolver import resolve_version, search_specs

__all__ = ["LocalRegistry", "resolve_version", "search_specs"]
