"""Cortex Cloud hosted agent-spec registry (client-side).

A sibling of `cortex_protocol.registry.local.LocalRegistry` that speaks
HTTP to Cortex Cloud instead of reading a directory on disk. Same public
surface (`publish`, `get`, `get_latest`, `list_agents`, `list_versions`,
`search`) so callers swap between local and cloud with one line.

Endpoint shape (agreed with the 0.5 backend plan):

    POST  /v1/registry/{workspace}/agents/{name}/versions
    GET   /v1/registry/{workspace}/agents/{name}/versions/{version}
    GET   /v1/registry/{workspace}/agents/{name}/latest
    GET   /v1/registry/{workspace}/agents/{name}/versions
    GET   /v1/registry/{workspace}/agents
    GET   /v1/registry/{workspace}/agents?tag=...&compliance=...&owner=...&q=...

All YAML payloads go over the wire as a JSON `{ "spec_yaml": "..." }`
envelope so the backend can index metadata without re-parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import AgentSpec
from ..registry.local import AgentMeta, PublishRecord
from .client import CloudAuthError, CloudClient, CloudHTTPError


@dataclass
class CloudRegistryError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


class CloudRegistry:
    """Hosted registry adapter. Requires Pro tier (hosted_registry feature)."""

    def __init__(self, client: CloudClient, workspace: str):
        if not workspace:
            raise CloudRegistryError(
                "A workspace is required for the Cloud registry. "
                "Set it via CORTEX_CLOUD_WORKSPACE or pass workspace=..."
            )
        self._client = client
        self._workspace = workspace

    @property
    def workspace(self) -> str:
        return self._workspace

    def _base(self) -> str:
        return f"/v1/registry/{self._workspace}/agents"

    # -----------------------------------------------------------------
    # publish
    # -----------------------------------------------------------------

    def publish(self, spec: AgentSpec, version: str) -> str:
        if not self._client.is_authenticated:
            raise CloudAuthError("Cloud registry requires login. Run `cortex-protocol login`.")
        name = spec.agent.name
        payload = {
            "version": version,
            "spec_yaml": spec.to_yaml(),
            "metadata": {
                "description": spec.agent.description,
                "tags": list(spec.metadata.tags) if spec.metadata else [],
                "compliance": list(spec.metadata.compliance) if spec.metadata else [],
                "owner": spec.metadata.owner if spec.metadata else "",
                "environment": spec.metadata.environment if spec.metadata else "",
            },
        }
        try:
            resp = self._client.request(
                "POST", f"{self._base()}/{name}/versions", body=payload,
            )
        except CloudHTTPError as e:
            if e.status == 409:
                raise CloudRegistryError(
                    f"Version {version} already exists for {name} in workspace {self._workspace}."
                ) from None
            raise
        return (resp or {}).get("url", "")

    # -----------------------------------------------------------------
    # get
    # -----------------------------------------------------------------

    def get(self, name: str, version: str) -> Optional[AgentSpec]:
        try:
            resp = self._client.request(
                "GET", f"{self._base()}/{name}/versions/{version}",
            )
        except CloudHTTPError as e:
            if e.status == 404:
                return None
            raise
        return _spec_from_response(resp)

    def get_latest(self, name: str) -> Optional[AgentSpec]:
        try:
            resp = self._client.request("GET", f"{self._base()}/{name}/latest")
        except CloudHTTPError as e:
            if e.status == 404:
                return None
            raise
        return _spec_from_response(resp)

    # -----------------------------------------------------------------
    # list / search
    # -----------------------------------------------------------------

    def list_agents(self) -> list[AgentMeta]:
        resp = self._client.request("GET", self._base())
        return [_meta_from_response(x) for x in (resp or {}).get("agents", [])]

    def list_versions(self, name: str) -> list[str]:
        try:
            resp = self._client.request("GET", f"{self._base()}/{name}/versions")
        except CloudHTTPError as e:
            if e.status == 404:
                return []
            raise
        return [v["version"] for v in (resp or {}).get("versions", [])]

    def search(
        self,
        *,
        tags: Optional[list[str]] = None,
        compliance: Optional[list[str]] = None,
        owner: Optional[str] = None,
        name_contains: Optional[str] = None,
    ) -> list[tuple[AgentMeta, AgentSpec]]:
        params: list[str] = []
        if tags:
            params.extend(f"tag={_encode(t)}" for t in tags)
        if compliance:
            params.extend(f"compliance={_encode(c)}" for c in compliance)
        if owner:
            params.append(f"owner={_encode(owner)}")
        if name_contains:
            params.append(f"q={_encode(name_contains)}")
        q = ("?" + "&".join(params)) if params else ""
        resp = self._client.request("GET", f"{self._base()}{q}")
        results: list[tuple[AgentMeta, AgentSpec]] = []
        for item in (resp or {}).get("agents", []):
            spec_yaml = item.get("latest_spec_yaml")
            if not spec_yaml:
                continue
            results.append((_meta_from_response(item), AgentSpec.from_yaml_str(spec_yaml)))
        return results


def _encode(value: str) -> str:
    import urllib.parse
    return urllib.parse.quote(value, safe="")


def _spec_from_response(resp: dict) -> Optional[AgentSpec]:
    if not resp:
        return None
    yaml_text = resp.get("spec_yaml")
    if not yaml_text:
        return None
    return AgentSpec.from_yaml_str(yaml_text)


def _meta_from_response(item: dict) -> AgentMeta:
    return AgentMeta(
        name=item.get("name", ""),
        latest=item.get("latest", ""),
        versions=[
            PublishRecord(
                version=v.get("version", ""),
                published_at=v.get("published_at", ""),
                spec_file=v.get("spec_file", ""),
            )
            for v in item.get("versions", [])
        ],
    )
