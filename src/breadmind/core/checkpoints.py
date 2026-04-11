"""Track file edits, rewind to previous states, and fork conversations."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from breadmind.utils.helpers import generate_short_id


@dataclass
class FileSnapshot:
    """A snapshot of a single file's content at a point in time."""

    path: str
    content: str
    timestamp: float


@dataclass
class Checkpoint:
    """A named save point with file snapshots."""

    id: str
    label: str
    timestamp: float
    snapshots: list[FileSnapshot] = field(default_factory=list)
    message_index: int = 0  # Position in conversation
    parent_id: str | None = None  # For forking


class CheckpointManager:
    """Track file edits, rewind to previous states, fork conversations.

    Creates automatic checkpoints before file modifications.
    Supports manual checkpoints for named save points.
    """

    def __init__(self, storage_dir: Path | None = None):
        self._storage_dir = storage_dir or Path.home() / ".breadmind" / "checkpoints"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoints: list[Checkpoint] = []
        self._current_index: int = -1

    def create(
        self,
        label: str = "",
        files: list[str] | None = None,
        message_index: int = 0,
    ) -> Checkpoint:
        """Create a new checkpoint, optionally snapshotting specific files."""
        cp_id = generate_short_id(12)
        now = time.time()
        snapshots: list[FileSnapshot] = []

        if files:
            for fpath in files:
                p = Path(fpath)
                if p.is_file():
                    try:
                        content = p.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        content = ""
                    snapshots.append(
                        FileSnapshot(path=str(p), content=content, timestamp=now)
                    )

        parent_id = None
        if self._current_index >= 0 and self._current_index < len(self._checkpoints):
            parent_id = self._checkpoints[self._current_index].id

        cp = Checkpoint(
            id=cp_id,
            label=label or f"checkpoint-{cp_id}",
            timestamp=now,
            snapshots=snapshots,
            message_index=message_index,
            parent_id=parent_id,
        )

        # If we're not at the end, trim future checkpoints (linear history)
        if self._current_index < len(self._checkpoints) - 1:
            self._checkpoints = self._checkpoints[: self._current_index + 1]

        self._checkpoints.append(cp)
        self._current_index = len(self._checkpoints) - 1
        return cp

    def snapshot_file(self, checkpoint_id: str, file_path: str) -> None:
        """Add a file snapshot to an existing checkpoint."""
        cp = self.get(checkpoint_id)
        if cp is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"File {file_path} not found")

        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise OSError(f"Cannot read {file_path}: {exc}") from exc

        cp.snapshots.append(
            FileSnapshot(path=str(p), content=content, timestamp=time.time())
        )

    def rewind(self, checkpoint_id: str) -> list[FileSnapshot]:
        """Rewind to a checkpoint. Returns list of files that would be restored.

        Does NOT actually restore files (caller decides).
        """
        cp = self.get(checkpoint_id)
        if cp is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        # Update current index
        idx = self._find_index(checkpoint_id)
        if idx is not None:
            self._current_index = idx

        return list(cp.snapshots)

    def restore(self, checkpoint_id: str) -> list[str]:
        """Actually restore files from a checkpoint. Returns list of restored paths."""
        snapshots = self.rewind(checkpoint_id)
        restored: list[str] = []

        for snap in snapshots:
            p = Path(snap.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(snap.content, encoding="utf-8")
            restored.append(snap.path)

        return restored

    def fork(self, checkpoint_id: str, label: str = "") -> Checkpoint:
        """Create a fork from a checkpoint (for conversation branching)."""
        source = self.get(checkpoint_id)
        if source is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        cp_id = generate_short_id(12)
        now = time.time()

        # Copy snapshots from source
        forked_snapshots = [
            FileSnapshot(path=s.path, content=s.content, timestamp=s.timestamp)
            for s in source.snapshots
        ]

        cp = Checkpoint(
            id=cp_id,
            label=label or f"fork-{cp_id}",
            timestamp=now,
            snapshots=forked_snapshots,
            message_index=source.message_index,
            parent_id=checkpoint_id,
        )
        self._checkpoints.append(cp)
        self._current_index = len(self._checkpoints) - 1
        return cp

    def list_checkpoints(self) -> list[Checkpoint]:
        """List all checkpoints."""
        return list(self._checkpoints)

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a checkpoint by ID."""
        for cp in self._checkpoints:
            if cp.id == checkpoint_id:
                return cp
        return None

    def save_to_disk(self) -> None:
        """Persist checkpoint metadata to storage."""
        data = []
        for cp in self._checkpoints:
            data.append(
                {
                    "id": cp.id,
                    "label": cp.label,
                    "timestamp": cp.timestamp,
                    "message_index": cp.message_index,
                    "parent_id": cp.parent_id,
                    "snapshots": [
                        {
                            "path": s.path,
                            "content": s.content,
                            "timestamp": s.timestamp,
                        }
                        for s in cp.snapshots
                    ],
                }
            )
        meta = {"checkpoints": data, "current_index": self._current_index}
        meta_path = self._storage_dir / "checkpoints.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def load_from_disk(self) -> None:
        """Load checkpoint metadata from storage."""
        meta_path = self._storage_dir / "checkpoints.json"
        if not meta_path.is_file():
            return

        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        self._checkpoints = []
        for item in raw.get("checkpoints", []):
            snapshots = [
                FileSnapshot(
                    path=s["path"],
                    content=s["content"],
                    timestamp=s["timestamp"],
                )
                for s in item.get("snapshots", [])
            ]
            self._checkpoints.append(
                Checkpoint(
                    id=item["id"],
                    label=item["label"],
                    timestamp=item["timestamp"],
                    snapshots=snapshots,
                    message_index=item.get("message_index", 0),
                    parent_id=item.get("parent_id"),
                )
            )
        self._current_index = raw.get("current_index", len(self._checkpoints) - 1)

    def _find_index(self, checkpoint_id: str) -> int | None:
        """Find the list index of a checkpoint by ID."""
        for i, cp in enumerate(self._checkpoints):
            if cp.id == checkpoint_id:
                return i
        return None
