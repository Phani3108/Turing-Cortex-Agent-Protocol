"""Schema migration functions for Cortex Protocol specs."""
from .v01_to_v03 import migrate_v01_to_v03

MIGRATIONS = {"0.1": migrate_v01_to_v03}

_LATEST_VERSION = "0.3"


def migrate(spec_dict: dict, from_version: str = None) -> dict:
    """Migrate a spec dict to the latest schema version."""
    version = from_version or spec_dict.get("version", "0.1")

    if version == _LATEST_VERSION:
        return spec_dict

    fn = MIGRATIONS.get(version)
    if fn is None:
        return spec_dict

    return fn(spec_dict)
