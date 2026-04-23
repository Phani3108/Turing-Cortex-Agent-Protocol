"""Cortex Cloud — OSS-side integration.

This package is a no-op when no Cloud URL / credentials are configured.
Everything here is either:

  - A thin HTTP client against Cortex Cloud endpoints, or
  - An adapter that plugs Turing's existing surfaces (registry, audit log,
    approval handler) into the Cloud transport.

Env vars the Cloud subsystem reads:

    CORTEX_CLOUD_URL        Base URL for the Cloud API (default: https://cloud.cortexprotocol.dev)
    CORTEX_CLOUD_TOKEN      PAT / OIDC access token. CI-friendly alternative to `login`.
    CORTEX_CLOUD_WORKSPACE  Workspace slug to scope operations to.
"""

from __future__ import annotations

from .client import (
    CloudAuthError,
    CloudClient,
    CloudHTTPError,
    Credentials,
    default_cloud_url,
    load_credentials,
    save_credentials,
)
from .audit_exporter import CloudAuditExporter, drain_fallback
from .registry import CloudRegistry, CloudRegistryError

__all__ = [
    "CloudAuthError",
    "CloudClient",
    "CloudHTTPError",
    "Credentials",
    "default_cloud_url",
    "load_credentials",
    "save_credentials",
    "CloudAuditExporter",
    "drain_fallback",
    "CloudRegistry",
    "CloudRegistryError",
]
