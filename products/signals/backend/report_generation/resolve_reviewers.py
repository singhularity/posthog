from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

import requests

from posthog.models.integration import GitHubIntegration, Integration

logger = logging.getLogger(__name__)

MAX_SUGGESTED_REVIEWERS = 3


@dataclass
class EnrichedReviewer:
    """A suggested reviewer, optionally linked to a PostHog user."""

    github_login: str
    user_id: int | None = None
    user_uuid: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    hedgehog_config: dict | None = None

    def to_dict(self) -> dict:
        return {
            "github_login": self.github_login,
            "user": {
                "id": self.user_id,
                "uuid": self.user_uuid,
                "first_name": self.first_name,
                "last_name": self.last_name,
                "email": self.email,
                "hedgehog_config": self.hedgehog_config,
            }
            if self.user_id is not None
            else None,
        }


def _get_github_integration(team_id: int) -> GitHubIntegration | None:
    """Get the first available GitHub integration for the team."""
    integration = Integration.objects.filter(team_id=team_id, kind="github").first()
    if integration is None:
        return None
    return GitHubIntegration(integration)


def _resolve_commit_author(github: GitHubIntegration, repo: str, sha: str) -> str | None:
    """Resolve a commit SHA to a GitHub login via the GitHub API."""
    if github.access_token_expired():
        try:
            github.refresh_access_token()
        except Exception:
            logger.warning("Failed to refresh GitHub token for commit resolution", exc_info=True)
            return None

    access_token = github.integration.sensitive_config.get("access_token")
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repo}/commits/{sha}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        if response.status_code != 200:
            logger.info("GitHub API returned %d for commit %s in %s", response.status_code, sha[:8], repo)
            return None
        data = response.json()
        author = data.get("author")
        if author and author.get("login"):
            return author["login"]
    except Exception:
        logger.warning("Failed to resolve commit %s in %s", sha[:8], repo, exc_info=True)
    return None


def resolve_suggested_reviewers(
    team_id: int,
    repository: str,
    commit_hashes: list[str],
) -> list[str]:
    """Resolve commit hashes to up to 3 GitHub logins, ordered by relevance.

    Commits earlier in the list are weighted more heavily (they come from
    higher-priority findings and more critical code paths).
    """
    if not commit_hashes or not repository:
        return []

    github = _get_github_integration(team_id)
    if github is None:
        logger.info("No GitHub integration for team %d, cannot resolve reviewers", team_id)
        return []

    # Weight earlier commits more heavily (position-based weighting)
    login_weights: Counter[str] = Counter()
    seen_shas: set[str] = set()

    for i, sha in enumerate(commit_hashes):
        if sha in seen_shas:
            continue
        seen_shas.add(sha)

        login = _resolve_commit_author(github, repository, sha)
        if login:
            # Earlier commits get higher weight: first commit gets weight N, last gets 1
            weight = len(commit_hashes) - i
            login_weights[login] += weight

    # Return top reviewers by weighted score
    return [login for login, _ in login_weights.most_common(MAX_SUGGESTED_REVIEWERS)]


def enrich_reviewers_with_org_members(
    team_id: int,
    github_logins: list[str],
) -> list[EnrichedReviewer]:
    """Enrich GitHub logins with PostHog user info by matching via social auth.

    Returns EnrichedReviewer objects. When a GitHub login matches an org member
    who signed in with GitHub, the user info is populated; otherwise only
    github_login is set.
    """
    from social_django.models import UserSocialAuth

    from posthog.models.team.team import Team

    if not github_logins:
        return []

    try:
        org_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
    except Team.DoesNotExist:
        return [EnrichedReviewer(github_login=login) for login in github_logins]

    # Fetch all GitHub social auth records for org members in one query
    social_auths = (
        UserSocialAuth.objects.filter(
            provider="github",
            user__organization_memberships__organization_id=org_id,
        )
        .select_related("user")
        .only(
            "extra_data",
            "user__id",
            "user__uuid",
            "user__first_name",
            "user__last_name",
            "user__email",
            "user__hedgehog_config",
        )
    )

    # Build login -> User mapping
    login_to_user: dict[str, Any] = {}
    for sa in social_auths:
        extra = sa.extra_data
        if isinstance(extra, dict):
            login = extra.get("login")
        else:
            continue
        if login:
            login_to_user[login.lower()] = sa.user

    enriched: list[EnrichedReviewer] = []
    for login in github_logins:
        user = login_to_user.get(login.lower())
        if user is not None:
            enriched.append(
                EnrichedReviewer(
                    github_login=login,
                    user_id=user.id,
                    user_uuid=str(user.uuid),
                    first_name=user.first_name,
                    last_name=user.last_name,
                    email=user.email,
                    hedgehog_config=user.hedgehog_config,
                )
            )
        else:
            enriched.append(EnrichedReviewer(github_login=login))

    return enriched


def get_github_login_for_user(user_id: int) -> str | None:
    """Get the GitHub login for a PostHog user via their social auth record."""
    from social_django.models import UserSocialAuth

    sa = UserSocialAuth.objects.filter(provider="github", user_id=user_id).first()
    if sa is None:
        return None
    extra = sa.extra_data
    if isinstance(extra, dict):
        return extra.get("login")
    return None
