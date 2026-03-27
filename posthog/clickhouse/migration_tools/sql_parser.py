from __future__ import annotations

import re
from pathlib import Path

from posthog.clickhouse.migration_tools.manifest import ManifestStep


def parse_sql_sections(content: str) -> dict[str, str]:
    """Parse SQL file into named sections delimited by `-- @section: name` comments.

    Returns a dict mapping section name to SQL content. If no section markers
    are found, the entire content is returned under the key "default".
    """
    section_pattern = re.compile(r"^--\s*@section:\s*(\S+)\s*$", re.MULTILINE)

    matches = list(section_pattern.finditer(content))

    if not matches:
        return {"default": content.strip()}

    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = match.group(1)
        if name in sections:
            raise ValueError(f"Duplicate section name '{name}' in SQL file")
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_sql = content[start:end].strip()
        sections[name] = section_sql

    return sections


def get_sql_for_step(migration_dir: Path, step: ManifestStep) -> str:
    """Get raw SQL content for a manifest step.

    Handles the `file#section` syntax. If no section is specified,
    returns the entire file content.
    """
    if "#" in step.sql:
        filename, section = step.sql.split("#", 1)
    else:
        filename = step.sql
        section = None

    sql_path = migration_dir / filename
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    content = sql_path.read_text()

    if section is None:
        return content.strip()

    sections = parse_sql_sections(content)
    if section not in sections:
        raise KeyError(f"Section '{section}' not found in {filename}. Available sections: {sorted(sections.keys())}")

    return sections[section]
