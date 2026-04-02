"""GitHub-backed remote registry for sharing agent specs.

Uses GitHub API to read from a repo's registry/ directory.
Auth via GITHUB_TOKEN env var (optional for public repos).
Uses only urllib.request - no extra deps.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from ..models import AgentSpec
from .local import AgentMeta, PublishRecord


class RemoteRegistry:
    """GitHub-backed remote registry for sharing agent specs."""

    def __init__(self, repo: str, branch: str = "main", token: str = None):
        """repo: 'owner/repo-name'"""
        self._repo = repo
        self._branch = branch
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._api_base = "https://api.github.com"
        self._raw_base = "https://raw.githubusercontent.com"

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "cortex-protocol"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _get_json(self, url: str) -> Optional[dict | list]:
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def _get_raw(self, path: str) -> Optional[str]:
        url = f"{self._raw_base}/{self._repo}/{self._branch}/{path}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def _put_file(self, path: str, content: str, message: str, sha: str = None) -> dict:
        import base64
        url = f"{self._api_base}/repos/{self._repo}/contents/{path}"
        body = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": self._branch,
        }
        if sha:
            body["sha"] = sha
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers={
            **self._headers(),
            "Content-Type": "application/json",
        }, method="PUT")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())

    def get(self, name: str, version: str) -> Optional[AgentSpec]:
        content = self._get_raw(f"registry/{name}/{version}.yaml")
        if content is None:
            return None
        return AgentSpec.from_yaml_str(content)

    def get_latest(self, name: str) -> Optional[AgentSpec]:
        meta_content = self._get_raw(f"registry/{name}/meta.json")
        if meta_content is None:
            return None
        meta_data = json.loads(meta_content)
        latest = meta_data.get("latest", "")
        if not latest:
            return None
        return self.get(name, latest)

    def list_agents(self) -> list[AgentMeta]:
        url = f"{self._api_base}/repos/{self._repo}/contents/registry?ref={self._branch}"
        data = self._get_json(url)
        if not data or not isinstance(data, list):
            return []

        agents = []
        for item in data:
            if item.get("type") == "dir":
                name = item["name"]
                meta_content = self._get_raw(f"registry/{name}/meta.json")
                if meta_content:
                    meta_data = json.loads(meta_content)
                    agents.append(AgentMeta.from_dict(meta_data))
        return agents

    def list_versions(self, name: str) -> list[str]:
        meta_content = self._get_raw(f"registry/{name}/meta.json")
        if meta_content is None:
            return []
        meta_data = json.loads(meta_content)
        return [v["version"] for v in meta_data.get("versions", [])]

    def search(
        self,
        tags=None,
        compliance=None,
        owner=None,
        name_contains=None,
    ) -> list[dict]:
        """Search agents by metadata. Returns list of result dicts."""
        results = []
        for meta in self.list_agents():
            spec = self.get_latest(meta.name)
            if not spec:
                continue

            md = spec.metadata
            if tags and md:
                if not all(t in md.tags for t in tags):
                    continue
            elif tags and not md:
                continue

            if compliance and md:
                if not all(c in md.compliance for c in compliance):
                    continue
            elif compliance and not md:
                continue

            if owner:
                if not md or md.owner != owner:
                    continue

            if name_contains:
                if name_contains.lower() not in meta.name.lower():
                    continue

            results.append({
                "name": meta.name,
                "version": meta.latest,
                "description": spec.agent.description,
                "owner": spec.metadata.owner if spec.metadata else "",
                "tags": spec.metadata.tags if spec.metadata else [],
                "compliance": spec.metadata.compliance if spec.metadata else [],
            })

        return results

    def publish(self, spec: AgentSpec, version: str) -> str:
        """Create/update file in GitHub repo via API. Returns URL."""
        name = spec.agent.name
        spec_path = f"registry/{name}/{version}.yaml"
        meta_path = f"registry/{name}/meta.json"

        # Write spec file
        yaml_content = spec.to_yaml()
        spec_url = f"{self._api_base}/repos/{self._repo}/contents/{spec_path}"
        existing = self._get_json(spec_url)
        sha = existing.get("sha") if existing else None
        result = self._put_file(
            spec_path,
            yaml_content,
            f"Publish {name}@{version}",
            sha=sha,
        )

        # Update meta.json
        from datetime import datetime, timezone
        meta_content_raw = self._get_raw(meta_path)
        if meta_content_raw:
            meta_data = json.loads(meta_content_raw)
            meta_sha_resp = self._get_json(
                f"{self._api_base}/repos/{self._repo}/contents/{meta_path}"
            )
            meta_sha = meta_sha_resp.get("sha") if meta_sha_resp else None
        else:
            meta_data = {"name": name, "latest": "", "versions": []}
            meta_sha = None

        meta_data["latest"] = version
        meta_data["versions"].append({
            "version": version,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "spec_file": f"{version}.yaml",
        })
        self._put_file(
            meta_path,
            json.dumps(meta_data, indent=2),
            f"Update meta for {name}@{version}",
            sha=meta_sha,
        )

        html_url = result.get("content", {}).get("html_url", spec_path)
        return html_url
