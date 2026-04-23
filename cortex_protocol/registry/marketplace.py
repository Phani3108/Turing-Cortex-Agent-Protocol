"""Policy pack marketplace — local store + Cloud adapter.

A "policy pack" is a shareable YAML document that bundles a
`PolicySpec`-shaped block under a versioned name. Specs reference an
installed pack via `policies.from_template: "<pack-name>"`, identical to
the built-in template names — installed packs just extend the template
registry at runtime.

Local layout:
    <data_dir>/policy-packs/<pack_name>/<version>.yaml
    <data_dir>/policy-packs/<pack_name>/meta.json   # {latest, versions[]}

Cloud adapter (enabled by Pro tier) sits on top of `CloudClient` and
speaks the existing registry HTTP idioms against
    GET  /v1/marketplace/packs
    GET  /v1/marketplace/packs/{name}/versions/{version}
    POST /v1/marketplace/packs/{name}/versions
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from ..models import PolicySpec
from ..platform import data_dir, ensure_dir


POLICY_PACKS_DIRNAME = "policy-packs"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PolicyPack:
    """One versioned policy pack ready to be installed or consumed."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = "MIT"
    tags: list[str] = field(default_factory=list)
    compliance: list[str] = field(default_factory=list)
    policy: dict = field(default_factory=dict)    # raw PolicySpec dict

    def to_yaml(self) -> str:
        return yaml.dump(asdict(self), sort_keys=False, default_flow_style=False)

    @classmethod
    def from_yaml(cls, text: str) -> "PolicyPack":
        data = yaml.safe_load(text) or {}
        return cls(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            license=data.get("license", "MIT"),
            tags=list(data.get("tags") or []),
            compliance=list(data.get("compliance") or []),
            policy=dict(data.get("policy") or {}),
        )

    def as_policy_spec(self) -> PolicySpec:
        return PolicySpec.model_validate(self.policy)


@dataclass
class PackMeta:
    name: str
    latest: str = ""
    versions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PackMeta":
        return cls(name=data["name"],
                    latest=data.get("latest", ""),
                    versions=list(data.get("versions") or []))


# ---------------------------------------------------------------------------
# Local marketplace
# ---------------------------------------------------------------------------

class LocalPolicyMarketplace:
    """File-based marketplace under `data_dir()/policy-packs/`."""

    def __init__(self, root: Optional[Path] = None):
        self._root = root or (data_dir() / POLICY_PACKS_DIRNAME)

    @property
    def root(self) -> Path:
        return self._root

    def _pack_dir(self, name: str) -> Path:
        return self._root / name

    def _meta_path(self, name: str) -> Path:
        return self._pack_dir(name) / "meta.json"

    # ---- publish / get -----------------------------------------------

    def install(self, pack: PolicyPack) -> Path:
        """Write a pack to the local store. Idempotent per (name, version)."""
        ensure_dir(self._pack_dir(pack.name))
        spec_path = self._pack_dir(pack.name) / f"{pack.version}.yaml"
        spec_path.write_text(pack.to_yaml())

        meta = self._load_meta(pack.name) or PackMeta(name=pack.name)
        if pack.version not in meta.versions:
            meta.versions.append(pack.version)
        meta.latest = _max_semver(meta.versions)
        self._meta_path(pack.name).write_text(json.dumps(meta.to_dict(), indent=2))
        return spec_path

    def get(self, name: str, version: Optional[str] = None) -> Optional[PolicyPack]:
        meta = self._load_meta(name)
        if meta is None:
            return None
        v = version or meta.latest
        if not v:
            return None
        spec_path = self._pack_dir(name) / f"{v}.yaml"
        if not spec_path.exists():
            return None
        return PolicyPack.from_yaml(spec_path.read_text())

    def list_packs(self) -> list[PackMeta]:
        if not self._root.exists():
            return []
        out: list[PackMeta] = []
        for child in sorted(self._root.iterdir()):
            if not child.is_dir():
                continue
            meta = self._load_meta(child.name)
            if meta is not None:
                out.append(meta)
        return out

    def uninstall(self, name: str) -> bool:
        pdir = self._pack_dir(name)
        if not pdir.exists():
            return False
        import shutil
        shutil.rmtree(pdir)
        return True

    def search(
        self,
        *,
        tag: Optional[str] = None,
        compliance: Optional[str] = None,
        query: Optional[str] = None,
    ) -> list[PolicyPack]:
        results: list[PolicyPack] = []
        for meta in self.list_packs():
            pack = self.get(meta.name)
            if pack is None:
                continue
            if tag and tag not in pack.tags:
                continue
            if compliance and compliance not in pack.compliance:
                continue
            if query:
                hay = " ".join([pack.name, pack.description, *pack.tags]).lower()
                if query.lower() not in hay:
                    continue
            results.append(pack)
        return results

    # ---- integration with policy template system --------------------

    def register_installed_packs_as_templates(self) -> list[str]:
        """Expose every installed pack's policy as a named `from_template` entry.

        Callers invoke this once at CLI startup so `policies.from_template:
        "my-org-payment"` resolves against the installed marketplace.
        Returns the list of template names now available.
        """
        from ..governance.templates import register_template

        names: list[str] = []
        for meta in self.list_packs():
            pack = self.get(meta.name)
            if pack is None:
                continue
            try:
                register_template(pack.name, pack.as_policy_spec())
                names.append(pack.name)
            except Exception:
                # Skip malformed packs rather than crash CLI startup.
                continue
        return names

    # ---- internals ---------------------------------------------------

    def _load_meta(self, name: str) -> Optional[PackMeta]:
        mpath = self._meta_path(name)
        if not mpath.exists():
            return None
        return PackMeta.from_dict(json.loads(mpath.read_text()))


def _max_semver(versions: Iterable[str]) -> str:
    """Return the highest numeric-semver-looking value; falls back to string max."""
    def key(v: str) -> tuple:
        parts = v.split(".")
        ints = []
        for p in parts:
            try:
                ints.append(int(p))
            except ValueError:
                ints.append(0)
        return tuple(ints)

    return max(versions, key=key) if versions else ""


# ---------------------------------------------------------------------------
# Cloud marketplace (thin wrapper on CloudClient)
# ---------------------------------------------------------------------------

class CloudPolicyMarketplace:
    """Pro-tier adapter. Hits Cortex Cloud marketplace endpoints."""

    def __init__(self, client: Any):
        self._client = client

    def search(self, *, tag: Optional[str] = None,
                compliance: Optional[str] = None,
                query: Optional[str] = None) -> list[PolicyPack]:
        params: list[str] = []
        if tag:
            params.append(f"tag={_q(tag)}")
        if compliance:
            params.append(f"compliance={_q(compliance)}")
        if query:
            params.append(f"q={_q(query)}")
        q = ("?" + "&".join(params)) if params else ""
        resp = self._client.request("GET", f"/v1/marketplace/packs{q}")
        return [_pack_from_response(p) for p in (resp or {}).get("packs", [])]

    def get(self, name: str, version: Optional[str] = None) -> Optional[PolicyPack]:
        path = f"/v1/marketplace/packs/{name}/latest" if not version \
            else f"/v1/marketplace/packs/{name}/versions/{version}"
        try:
            resp = self._client.request("GET", path)
        except Exception:
            return None
        if not resp:
            return None
        return _pack_from_response(resp)

    def publish(self, pack: PolicyPack) -> str:
        resp = self._client.request(
            "POST", f"/v1/marketplace/packs/{pack.name}/versions",
            body={"version": pack.version, "pack_yaml": pack.to_yaml()},
        )
        return (resp or {}).get("url", "")


def _q(v: str) -> str:
    import urllib.parse
    return urllib.parse.quote(v, safe="")


def _pack_from_response(data: dict) -> PolicyPack:
    # Endpoints may return either a nested `pack_yaml` or a flat dict.
    if "pack_yaml" in data and data["pack_yaml"]:
        return PolicyPack.from_yaml(data["pack_yaml"])
    return PolicyPack(
        name=data.get("name", ""),
        version=data.get("version", ""),
        description=data.get("description", ""),
        author=data.get("author", ""),
        license=data.get("license", "MIT"),
        tags=list(data.get("tags") or []),
        compliance=list(data.get("compliance") or []),
        policy=dict(data.get("policy") or {}),
    )
