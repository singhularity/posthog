from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import requests

from posthog.models.integration import GitHubIntegration, Integration

logger = logging.getLogger(__name__)

MAX_SUGGESTED_REVIEWERS = 3


@dataclass
class RelevantCommit:
    """A commit that was identified as relevant to a signal finding."""

    sha: str
    url: str

    def to_dict(self) -> dict:
        return {"sha": self.sha, "url": self.url}


@dataclass
class EnrichedReviewer:
    """A suggested reviewer, optionally linked to a PostHog user."""

    github_login: str
    github_name: str | None = None
    relevant_commits: list[RelevantCommit] = field(default_factory=list)
    user_id: int | None = None
    user_uuid: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    hedgehog_config: dict | None = None

    def to_dict(self) -> dict:
        return {
            "github_login": self.github_login,
            "github_name": self.github_name,
            "relevant_commits": [c.to_dict() for c in self.relevant_commits],
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


@dataclass
class _CommitAuthorInfo:
    login: str
    name: str | None
    commit_url: str


def _resolve_commit_author(github: GitHubIntegration, repo: str, sha: str) -> _CommitAuthorInfo | None:
    """Resolve a commit SHA to author info via the GitHub API."""
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
            # Get display name from the commit's git author (not the GH user object)
            git_author = data.get("commit", {}).get("author", {})
            name = git_author.get("name") or author.get("login")
            commit_url = data.get("html_url", f"https://github.com/{repo}/commit/{sha}")
            return _CommitAuthorInfo(login=author["login"], name=name, commit_url=commit_url)
    except Exception:
        logger.warning("Failed to resolve commit %s in %s", sha[:8], repo, exc_info=True)
    return None


@dataclass
class _ResolvedReviewer:
    """Intermediate result from commit resolution."""

    login: str
    name: str | None
    commits: list[RelevantCommit]
    weight: int


def resolve_suggested_reviewers(
    team_id: int,
    repository: str,
    commit_hashes: list[str],
) -> list[_ResolvedReviewer]:
    """Resolve commit hashes to up to 3 reviewers with their relevant commits.

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
    login_commits: dict[str, list[RelevantCommit]] = {}
    login_names: dict[str, str | None] = {}
    seen_shas: set[str] = set()

    for i, sha in enumerate(commit_hashes):
        if sha in seen_shas:
            continue
        seen_shas.add(sha)

        author_info = _resolve_commit_author(github, repository, sha)
        if author_info:
            login = author_info.login
            # Earlier commits get higher weight: first commit gets weight N, last gets 1
            weight = len(commit_hashes) - i
            login_weights[login] += weight
            login_commits.setdefault(login, []).append(RelevantCommit(sha=sha, url=author_info.commit_url))
            # Keep the first name we see (from highest-weight commit)
            if login not in login_names:
                login_names[login] = author_info.name

    # Return top reviewers by weighted score
    return [
        _ResolvedReviewer(
            login=login,
            name=login_names.get(login),
            commits=login_commits.get(login, []),
            weight=weight,
        )
        for login, weight in login_weights.most_common(MAX_SUGGESTED_REVIEWERS)
    ]


def enrich_reviewers_with_org_members(
    team_id: int,
    resolved_reviewers: list[_ResolvedReviewer],
) -> list[EnrichedReviewer]:
    """Enrich resolved reviewers with PostHog user info by matching via social auth.

    Returns EnrichedReviewer objects for all reviewers. When a GitHub login matches
    an org member who signed in with GitHub, the user info is populated; otherwise
    only github_login, github_name, and relevant_commits are set.
    """
    from social_django.models import UserSocialAuth

    from posthog.models.team.team import Team

    if not resolved_reviewers:
        return []

    try:
        org_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
    except Team.DoesNotExist:
        return [
            EnrichedReviewer(
                github_login=r.login,
                github_name=r.name,
                relevant_commits=r.commits,
            )
            for r in resolved_reviewers
        ]

    from posthog.models.organization import OrganizationMembership

    # Two-step: get org member user IDs, then fetch their GitHub social auth records
    org_member_user_ids = OrganizationMembership.objects.filter(
        organization_id=org_id,
    ).values_list("user_id", flat=True)

    social_auths = (
        UserSocialAuth.objects.filter(
            provider="github",
            user_id__in=org_member_user_ids,
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
    for r in resolved_reviewers:
        user = login_to_user.get(r.login.lower())
        reviewer = EnrichedReviewer(
            github_login=r.login,
            github_name=r.name,
            relevant_commits=r.commits,
        )
        if user is not None:
            reviewer.user_id = user.id
            reviewer.user_uuid = str(user.uuid)
            reviewer.first_name = user.first_name
            reviewer.last_name = user.last_name
            reviewer.email = user.email
            reviewer.hedgehog_config = user.hedgehog_config
        enriched.append(reviewer)

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
