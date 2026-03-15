from __future__ import annotations

import re
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMMessage
from breadmind.storage.models import EpisodicNote, KGEntity, KGRelation

if TYPE_CHECKING:
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.profiler import UserProfiler
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.memory.working import WorkingMemory

# Common English stopwords for keyword extraction
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "but", "and", "or", "if", "that", "this", "it", "i", "me", "my",
    "we", "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their", "what", "which", "who", "whom", "its", "about",
    "up", "down", "don", "t", "s", "re", "ve", "ll", "d", "m",
})

# Regex patterns for infrastructure entity extraction
_IP_PATTERN = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_HOSTNAME_PATTERN = re.compile(
    r"\b[a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z][a-zA-Z0-9-]*)+\b"
)
_INFRA_NAME_PATTERN = re.compile(
    r"\b(?:pod|svc|deploy|node|vm|container|namespace|ingress|service)"
    r"[-/][a-zA-Z0-9._-]+\b",
    re.IGNORECASE,
)


class ContextBuilder:
    """Build enriched context for LLM calls from all memory layers."""

    def __init__(
        self,
        working_memory: WorkingMemory,
        episodic_memory: EpisodicMemory | None = None,
        semantic_memory: SemanticMemory | None = None,
        profiler: UserProfiler | None = None,
        max_context_tokens: int = 4000,
    ):
        self._working = working_memory
        self._episodic = episodic_memory
        self._semantic = semantic_memory
        self._profiler = profiler
        self._max_context_tokens = max_context_tokens

    async def build_context(
        self, session_id: str, current_message: str
    ) -> list[LLMMessage]:
        """Build enriched context from all memory layers."""
        messages: list[LLMMessage] = []

        # 1. System prompt with user profile
        session = self._working._sessions.get(session_id)
        user = session.user if session else ""
        if self._profiler and user:
            profile_ctx = await self._profiler.get_user_context(user)
            if profile_ctx:
                messages.append(
                    LLMMessage(role="system", content=f"User profile:\n{profile_ctx}")
                )

        # 2. Relevant episodic memories (top 5 by keyword match)
        if self._episodic:
            keywords = self._extract_keywords(current_message)
            if keywords:
                episodes = await self._episodic.search_by_keywords(keywords, limit=5)
                if episodes:
                    context_text = "Relevant past experiences:\n" + "\n".join(
                        e.content for e in episodes
                    )
                    messages.append(LLMMessage(role="system", content=context_text))

        # 3. Related KG entities
        if self._semantic:
            keywords = self._extract_keywords(current_message)
            if keywords:
                entities = await self._semantic.get_context_for_query(
                    keywords, limit=5
                )
                if entities:
                    kg_text = "Known infrastructure context:\n" + "\n".join(
                        f"- {e.name}: {e.properties}" for e in entities
                    )
                    messages.append(LLMMessage(role="system", content=kg_text))

        # 4. Conversation history from working memory
        history = self._working.get_messages(session_id)
        messages.extend(history)

        return messages

    def _extract_keywords(self, text: str) -> list[str]:
        """Simple keyword extraction - split, filter stopwords, take top terms."""
        words = re.findall(r"[a-zA-Z0-9._-]+", text.lower())
        keywords = [w for w in words if w not in _STOPWORDS and len(w) > 1]
        # Deduplicate preserving order
        seen: set[str] = set()
        result: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
        return result

    async def promote_to_episodic(
        self, session_id: str, message_threshold: int = 10
    ) -> EpisodicNote | None:
        """Promote working memory conversation to an episodic note.

        Called when session ends or message count exceeds threshold.
        Summarizes key points using simple extraction (no LLM).
        """
        if not self._episodic:
            return None

        messages = self._working.get_messages(session_id)
        if not messages or len(messages) < message_threshold:
            return None

        # Build summary from user messages
        user_msgs = [m.content for m in messages if m.role == "user" and m.content]
        if not user_msgs:
            return None

        summary = "Session summary: " + " | ".join(user_msgs[:5])

        # Extract keywords from all messages
        all_text = " ".join(m.content for m in messages if m.content)
        keywords = self._extract_keywords(all_text)[:10]

        note = await self._episodic.add_note(
            content=summary,
            keywords=keywords,
            tags=["auto-promoted", f"session-{session_id}"],
            context_description=f"Promoted from session {session_id}",
        )
        return note

    async def promote_to_semantic(
        self, episodic_notes: list[EpisodicNote] | None = None,
    ) -> list[KGEntity]:
        """Scan episodic notes for entity patterns and create KG entries.

        Uses regex-based extraction for IPs, hostnames, and infrastructure names.
        """
        if not self._semantic:
            return []

        if episodic_notes is None and self._episodic:
            episodic_notes = await self._episodic.get_all_notes()

        if not episodic_notes:
            return []

        created_entities: list[KGEntity] = []
        seen_ids: set[str] = set()

        for note in episodic_notes:
            text = f"{note.content} {note.context_description}"

            # Extract IPs
            for ip in _IP_PATTERN.findall(text):
                entity_id = f"ip-{ip}"
                if entity_id not in seen_ids:
                    seen_ids.add(entity_id)
                    entity = KGEntity(
                        id=entity_id,
                        entity_type="infra_component",
                        name=ip,
                        properties={"type": "ip_address", "source_note": note.id},
                    )
                    await self._semantic.add_entity(entity)
                    created_entities.append(entity)

            # Extract hostnames
            for hostname in _HOSTNAME_PATTERN.findall(text):
                entity_id = f"host-{hostname}"
                if entity_id not in seen_ids:
                    seen_ids.add(entity_id)
                    entity = KGEntity(
                        id=entity_id,
                        entity_type="infra_component",
                        name=hostname,
                        properties={"type": "hostname", "source_note": note.id},
                    )
                    await self._semantic.add_entity(entity)
                    created_entities.append(entity)

            # Extract infra names (pod-xxx, svc-xxx, etc.)
            for infra_name in _INFRA_NAME_PATTERN.findall(text):
                entity_id = f"infra-{infra_name.lower()}"
                if entity_id not in seen_ids:
                    seen_ids.add(entity_id)
                    entity = KGEntity(
                        id=entity_id,
                        entity_type="infra_component",
                        name=infra_name,
                        properties={
                            "type": "infrastructure",
                            "source_note": note.id,
                        },
                    )
                    await self._semantic.add_entity(entity)
                    created_entities.append(entity)

        return created_entities

    async def auto_promote(self, message_threshold: int = 10) -> dict:
        """Automatically promote qualifying sessions to episodic, then to semantic.

        Returns summary of what was promoted.
        """
        import logging

        promoted = {"episodic_notes": 0, "semantic_entities": 0}

        if not self._working:
            return promoted

        # Phase 1: Promote qualifying working memory sessions to episodic
        new_notes = []
        session_ids = list(self._working._sessions.keys())
        for session_id in session_ids:
            try:
                note = await self.promote_to_episodic(session_id, message_threshold)
                if note:
                    new_notes.append(note)
                    promoted["episodic_notes"] += 1
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Failed to promote session {session_id}: {e}"
                )

        # Phase 2: Promote new episodic notes to semantic (extract entities)
        if new_notes and self._semantic:
            try:
                entities = await self.promote_to_semantic(new_notes)
                promoted["semantic_entities"] = len(entities) if entities else 0
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Failed to promote to semantic: {e}"
                )

        return promoted
