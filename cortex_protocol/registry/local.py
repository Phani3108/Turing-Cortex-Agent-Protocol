"""Local file-based agent registry.

Storage layout:
    ~/.cortex-protocol/registry/
        <agent-name>/
            1.0.0.yaml
            1.1.0.yaml
            2.0.0.yaml
            meta.json        # latest version, publish history

Each version is the full AgentSpec YAML. meta.json tracks versions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models import AgentSpec


DEFAULT_REGISTRY_DIR = Path.home() / ".cortex-protocol" / "registry"


@dataclass
class PublishRecord:
    version: str
    published_at: str  # ISO 8601
    spec_file: str     # filename in the agent directory


@dataclass
class AgentMeta:
    name: str
    latest: str = ""
    versions: list[PublishRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "latest": self.latest,
            "versions": [
                {"version": v.version, "published_at": v.published_at, "spec_file": v.spec_file}
                for v in self.versions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentMeta:
        return cls(
            name=data["name"],
            latest=data.get("latest", ""),
            versions=[
                PublishRecord(**v) for v in data.get("versions", [])
            ],
        )


_SEMVER_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def _parse_semver(v: str) -> tuple[int, int, int]:
    m = _SEMVER_RE.match(v.strip())
    if not m:
        raise ValueError(f"Invalid semver: {v!r}. Expected format: X.Y.Z (or X.Y or X)")
    return int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)


class LocalRegistry:
    """File-based versioned registry for agent specs.

    Usage:
        reg = LocalRegistry()                   # default ~/.cortex-protocol/registry/
        reg = LocalRegistry(Path("/custom"))     # custom directory

        reg.publish(spec, "1.0.0")              # publish a version
        spec = reg.get("my-agent", "1.0.0")     # retrieve specific version
        spec = reg.get_latest("my-agent")        # retrieve latest
        agents = reg.list_agents()               # list all agents
        versions = reg.list_versions("my-agent") # list all versions
        results = reg.search(tags=["payment"])   # search by metadata
    """

    def __init__(self, root: Optional[Path] = None):
        self._root = root or DEFAULT_REGISTRY_DIR

    @property
    def root(self) -> Path:
        return self._root

    def _agent_dir(self, name: str) -> Path:
        return self._root / name

    def _meta_path(self, name: str) -> Path:
        return self._agent_dir(name) / "meta.json"

    def _load_meta(self, name: str) -> Optional[AgentMeta]:
        path = self._meta_path(name)
        if not path.exists():
            return None
        return AgentMeta.from_dict(json.loads(path.read_text()))

    def _save_meta(self, meta: AgentMeta) -> None:
        path = self._meta_path(meta.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta.to_dict(), indent=2))

    # ------------------------------------------------------------------
    # publish
    # ------------------------------------------------------------------

    def publish(self, spec: AgentSpec, version: str) -> Path:
        """Publish an agent spec at a specific semver version.

        Returns the path to the written YAML file.
        Raises ValueError if version already exists or is not valid semver.
        """
        _parse_semver(version)  # validate
        name = spec.agent.name
        agent_dir = self._agent_dir(name)
        agent_dir.mkdir(parents=True, exist_ok=True)

        spec_file = f"{version}.yaml"
        spec_path = agent_dir / spec_file

        if spec_path.exists():
            raise ValueError(f"Version {version} already exists for {name}")

        meta = self._load_meta(name) or AgentMeta(name=name)

        # Check version is newer than latest
        if meta.latest:
            existing = _parse_semver(meta.latest)
            new = _parse_semver(version)
            if new <= existing:
                raise ValueError(
                    f"Version {version} must be greater than current latest {meta.latest}"
                )

        spec_path.write_text(spec.to_yaml())

        meta.latest = version
        meta.versions.append(PublishRecord(
            version=version,
            published_at=datetime.now(timezone.utc).isoformat(),
            spec_file=spec_file,
        ))
        self._save_meta(meta)

        return spec_path

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    def get(self, name: str, version: str) -> Optional[AgentSpec]:
        """Retrieve a specific version of an agent spec."""
        spec_path = self._agent_dir(name) / f"{version}.yaml"
        if not spec_path.exists():
            return None
        return AgentSpec.from_yaml(str(spec_path))

    def get_latest(self, name: str) -> Optional[AgentSpec]:
        """Retrieve the latest published version."""
        meta = self._load_meta(name)
        if not meta or not meta.latest:
            return None
        return self.get(name, meta.latest)

    def get_meta(self, name: str) -> Optional[AgentMeta]:
        """Get metadata for an agent (versions, publish dates)."""
        return self._load_meta(name)

    # ------------------------------------------------------------------
    # list / search
    # ------------------------------------------------------------------

    def list_agents(self) -> list[AgentMeta]:
        """List all agents in the registry."""
        if not self._root.exists():
            return []
        agents = []
        for d in sorted(self._root.iterdir()):
            if d.is_dir() and (d / "meta.json").exists():
                meta = self._load_meta(d.name)
                if meta:
                    agents.append(meta)
        return agents

    def list_versions(self, name: str) -> list[str]:
        """List all published versions for an agent."""
        meta = self._load_meta(name)
        if not meta:
            return []
        return [v.version for v in meta.versions]

    def search(
        self,
        tags: Optional[list[str]] = None,
        compliance: Optional[list[str]] = None,
        owner: Optional[str] = None,
        name_contains: Optional[str] = None,
    ) -> list[tuple[AgentMeta, AgentSpec]]:
        """Search agents by metadata fields.

        Returns list of (meta, latest_spec) tuples matching ALL criteria.
        """
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

            results.append((meta, spec))

        return results

    # ------------------------------------------------------------------
    # delete (for testing / cleanup)
    # ------------------------------------------------------------------

    def delete_agent(self, name: str) -> bool:
        """Remove an agent and all its versions from the registry."""
        import shutil
        agent_dir = self._agent_dir(name)
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
            return True
        return False
