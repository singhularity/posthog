from __future__ import annotations

import re

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

# Only simple alphanumeric + underscore variable names allowed,
# but must not start/end with double underscores (dunder protection).
_VALID_VARIABLE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_DUNDER_RE = re.compile(r"__\w+__|_\w+__")

# Patterns that indicate Jinja2 block or comment tags
_BLOCK_TAG_RE = re.compile(r"\{%")
_COMMENT_TAG_RE = re.compile(r"\{#")

# Pattern to find all {{ variable }} references
_VARIABLE_REF_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def create_migration_env() -> SandboxedEnvironment:
    """Create a restricted Jinja2 sandboxed environment for migration templates.

    Uses StrictUndefined to raise on unknown variables.
    """
    return SandboxedEnvironment(
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )


def _validate_template_source(template_str: str) -> None:
    """Pre-scan template source for forbidden constructs.

    Only {{ variable }} substitution is allowed. Block tags {% %} and
    comment tags {# #} are rejected before Jinja2 ever sees them.
    """
    if _BLOCK_TAG_RE.search(template_str):
        raise ValueError(
            "Jinja2 block tags ({% ... %}) are not allowed in migration SQL templates. "
            "Only {{ variable }} substitution is supported."
        )

    if _COMMENT_TAG_RE.search(template_str):
        raise ValueError(
            "Jinja2 comment tags ({# ... #}) are not allowed in migration SQL templates. "
            "Only {{ variable }} substitution is supported."
        )

    # Validate all variable references
    for match in _VARIABLE_REF_RE.finditer(template_str):
        var_name = match.group(1).strip()
        if not _VALID_VARIABLE_RE.match(var_name) or _DUNDER_RE.search(var_name):
            raise ValueError(
                f"Invalid variable name '{var_name}' in migration SQL template. "
                "Variable names must be alphanumeric with underscores, "
                "starting with a letter, and must not use dunder patterns."
            )


def render_sql(template_str: str, variables: dict[str, str]) -> str:
    """Render a SQL template string with the given variables.

    Pre-validates the template to reject block/comment tags and invalid
    variable names before rendering.
    """
    _validate_template_source(template_str)

    env = create_migration_env()
    template = env.from_string(template_str)
    return template.render(variables)
