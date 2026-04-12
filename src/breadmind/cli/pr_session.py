"""PR-Session linkage module -- resume sessions linked to pull requests."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PRSessionLink:
    pr_number: int
    pr_url: str
    session_id: str
    repo: str = ""
    created_at: float = 0


class PRSessionManager:
    """Manages session-PR linkage for iterative code review workflows.

    When a PR is created, the session ID is stored.
    --from-pr <number|url> resumes the linked session.
    """

    _STORAGE_FILE = "pr_links.json"

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or Path.home() / ".breadmind" / "pr_sessions"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._links: dict[int, PRSessionLink] = {}
        self._load()

    def link(
        self,
        pr_number: int,
        session_id: str,
        pr_url: str = "",
        repo: str = "",
    ) -> PRSessionLink:
        """Link a PR to a session."""
        link = PRSessionLink(
            pr_number=pr_number,
            pr_url=pr_url,
            session_id=session_id,
            repo=repo,
            created_at=time.time(),
        )
        self._links[pr_number] = link
        self._save()
        return link

    def get_session(self, pr_ref: str | int) -> PRSessionLink | None:
        """Get session link by PR number or URL.

        Parses URLs like 'https://github.com/owner/repo/pull/123'.
        """
        pr_number = self._parse_pr_ref(pr_ref)
        if pr_number is None:
            return None
        return self._links.get(pr_number)

    def list_links(self) -> list[PRSessionLink]:
        """Return all PR-session links sorted by creation time (newest first)."""
        return sorted(self._links.values(), key=lambda link: link.created_at, reverse=True)

    def unlink(self, pr_number: int) -> bool:
        """Remove a PR-session link. Returns True if it existed."""
        if pr_number in self._links:
            del self._links[pr_number]
            self._save()
            return True
        return False

    def _parse_pr_ref(self, ref: str | int) -> int | None:
        """Parse PR number from int, string number, or URL."""
        if isinstance(ref, int):
            return ref
        ref = str(ref).strip()
        # Try plain number
        if ref.isdigit():
            return int(ref)
        # Try GitHub PR URL pattern
        match = re.search(r"/pull/(\d+)", ref)
        if match:
            return int(match.group(1))
        return None

    def _save(self) -> None:
        path = self._storage_dir / self._STORAGE_FILE
        data = {
            str(num): {
                "pr_number": link.pr_number,
                "pr_url": link.pr_url,
                "session_id": link.session_id,
                "repo": link.repo,
                "created_at": link.created_at,
            }
            for num, link in self._links.items()
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        path = self._storage_dir / self._STORAGE_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for _key, entry in raw.items():
            link = PRSessionLink(
                pr_number=entry["pr_number"],
                pr_url=entry.get("pr_url", ""),
                session_id=entry["session_id"],
                repo=entry.get("repo", ""),
                created_at=entry.get("created_at", 0),
            )
            self._links[link.pr_number] = link
