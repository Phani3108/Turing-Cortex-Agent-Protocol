def migrate_v01_to_v03(spec_dict: dict) -> dict:
    """Migrate v0.1 spec to v0.3 format."""
    result = dict(spec_dict)
    result["version"] = "0.3"

    # Add metadata block if missing
    if "metadata" not in result:
        result["metadata"] = None

    # Add extends field if missing
    if "extends" not in result:
        result["extends"] = None

    # Add mcp: null on each tool if missing
    tools = result.get("tools", [])
    migrated_tools = []
    for tool in tools:
        t = dict(tool)
        if "mcp" not in t:
            t["mcp"] = None
        migrated_tools.append(t)
    result["tools"] = migrated_tools

    return result
