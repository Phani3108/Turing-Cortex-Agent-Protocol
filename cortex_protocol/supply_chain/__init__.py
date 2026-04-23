"""Supply-chain integrity for compiled agents.

Every artifact Turing produces (compiled agent directory, MCP server
bundle, evidence packet) can carry a tool-manifest: a signed JSON
document pinning every input that contributed to the build. Auditors +
CI gates consume the manifest to verify what ran matches what was
expected.

What goes in a manifest:
  - Cortex Protocol version used for compilation
  - Agent spec name, version, content hash (sha256)
  - Each declared tool, its MCP server package + version, and env vars
  - Preferred / fallback model IDs
  - Policy template references resolved during compile
  - Hash of every generated file

The manifest itself is Ed25519-signed (by the same key the audit chain
uses) so the full chain of custody — model → tools → policy → agent
code — is verifiable without trusting the filesystem.
"""

from __future__ import annotations

from .manifest import (
    AgentManifest,
    ManifestVerifyResult,
    ToolEntry,
    build_manifest,
    load_manifest,
    verify_manifest,
    write_manifest,
)

__all__ = [
    "AgentManifest",
    "ManifestVerifyResult",
    "ToolEntry",
    "build_manifest",
    "load_manifest",
    "verify_manifest",
    "write_manifest",
]
