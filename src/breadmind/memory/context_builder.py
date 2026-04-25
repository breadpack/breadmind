from __future__ import annotations

import asyncio
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from breadmind.llm.base import LLMMessage
from breadmind.memory.episodic_store import EpisodicFilter
from breadmind.memory.recall_render import render_recalled_episodes
from breadmind.storage.models import EpisodicNote, KGEntity, KGRelation

if TYPE_CHECKING:
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.episodic_store import EpisodicStore
    from breadmind.memory.profiler import UserProfiler
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.memory.working import WorkingMemory

logger = logging.getLogger(__name__)

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


class ContextProvider(ABC):
    """Plugin interface for injecting domain-specific context."""
    @abstractmethod
    async def get_context(self, session_id: str, message: str, intent: Any) -> list:
        """Return LLMMessage list based on current intent."""


class ContextBuilder:
    """Build enriched context for LLM calls from all memory layers."""

    def __init__(
        self,
        working_memory: WorkingMemory,
        episodic_memory: EpisodicMemory | None = None,
        semantic_memory: SemanticMemory | None = None,
        profiler: UserProfiler | None = None,
        max_context_tokens: int = 4000,
        skill_store=None,
        smart_retriever=None,
        episodic_store: EpisodicStore | None = None,
    ):
        self._working = working_memory
        self._episodic = episodic_memory
        self._semantic = semantic_memory
        self._profiler = profiler
        self._max_context_tokens = max_context_tokens
        self._skill_store = skill_store
        self._smart_retriever = smart_retriever
        self.episodic_store = episodic_store
        self._context_providers: list[ContextProvider] = []

    async def build_recalled_episodes(
        self, *, user_id: str | None, message: str,
    ) -> dict | None:
        """Per-turn weighted recall (T12).

        Looks up the top-K most relevant episodic notes for ``message`` and
        returns a Jinja2-rendered system message dict. Returns ``None`` when
        no store is configured, no notes match, or the store raises.

        ``K`` is read from ``BREADMIND_EPISODIC_RECALL_TURN_K`` (default 5).
        Failures are logged at warning level and swallowed so a recall miss
        never blocks the main LLM turn.
        """
        if self.episodic_store is None:
            return None
        try:
            k = int(os.getenv("BREADMIND_EPISODIC_RECALL_TURN_K", "5"))
            notes = await self.episodic_store.search(
                user_id=user_id,
                query=message,
                filters=EpisodicFilter(),
                limit=k,
            )
        except Exception as e:
            logger.warning(
                "ContextBuilder per-turn recall failed: %s", e, exc_info=True,
            )
            return None
        return render_recalled_episodes(notes)

    def register_provider(self, provider: ContextProvider) -> None:
        self._context_providers.append(provider)

    async def build_context(
        self, session_id: str, current_message: str, intent=None,
    ) -> list[LLMMessage]:
        """Build enriched context from all memory layers.

        Args:
            session_id: Session identifier.
            current_message: The user's current message.
            intent: Optional Intent object for intent-aware retrieval.
        """
        messages: list[LLMMessage] = []

        # 0. Intent context — tell the LLM what the user intends
        if intent is not None:
            from breadmind.core.intent import IntentCategory
            intent_desc = {
                IntentCategory.QUERY: "사용자가 정보를 조회하려고 합니다. 시스템 상태, 로그, 메트릭 등을 확인하세요.",
                IntentCategory.EXECUTE: "사용자가 작업 실행을 요청합니다. 조사 후 직접 실행하세요.",
                IntentCategory.DIAGNOSE: "사용자가 문제 진단을 요청합니다. 로그/상태를 조사하고 원인을 파악하세요.",
                IntentCategory.CONFIGURE: "사용자가 설정 변경을 요청합니다. 현재 설정을 확인 후 변경하세요.",
                IntentCategory.LEARN: "사용자가 기억/학습 관련 요청을 합니다. 기억을 저장하거나 검색하세요.",
                IntentCategory.CHAT: "일반 대화입니다.",
            }
            desc = intent_desc.get(intent.category, "")
            parts = [f"## Intent Analysis\n- Category: {intent.category.value}\n- Confidence: {intent.confidence:.0%}"]
            if desc:
                parts.append(f"- Guidance: {desc}")
            if intent.entities:
                parts.append(f"- Detected entities: {', '.join(intent.entities[:10])}")
            messages.append(LLMMessage(role="system", content="\n".join(parts)))

        # 1. System prompt with user profile
        session = self._working._sessions.get(session_id)
        user = session.user if session else ""
        if self._profiler and user:
            profile_ctx = await self._profiler.get_user_context(user)
            if profile_ctx:
                messages.append(
                    LLMMessage(role="system", content=f"User profile:\n{profile_ctx}")
                )

        # 1.5 Per-turn weighted recall (T12). Sits between the system prompt and
        # any history/context blocks so the LLM sees recalled facts before it
        # sees the conversation transcript.
        recalled = await self.build_recalled_episodes(
            user_id=user or None, message=current_message,
        )
        if recalled is not None:
            messages.append(
                LLMMessage(role=recalled["role"], content=recalled["content"])
            )

        # 2. Relevant context via SmartRetriever (semantic search) or fallback to keyword
        context_retrieved = False
        if self._smart_retriever:
            try:
                context_items = await asyncio.wait_for(
                    self._smart_retriever.retrieve_context(
                        current_message, token_budget=1500, limit=5,
                    ),
                    timeout=8,
                )
                if context_items:
                    ctx_lines = [f"- [{item.source}] {item.content}" for item in context_items]
                    messages.append(LLMMessage(
                        role="system",
                        content="Relevant past context:\n" + "\n".join(ctx_lines),
                    ))
                    context_retrieved = True
            except (asyncio.TimeoutError, Exception):
                pass

        # Fallback: keyword-based episodic search
        if not context_retrieved and self._episodic:
            keywords = self._extract_keywords(current_message)
            if keywords:
                try:
                    episodes = await asyncio.wait_for(
                        self._episodic.search_by_keywords(keywords, limit=5),
                        timeout=5,
                    )
                    if episodes:
                        context_text = "Relevant past experiences:\n" + "\n".join(
                            e.content for e in episodes
                        )
                        messages.append(LLMMessage(role="system", content=context_text))
                except (asyncio.TimeoutError, Exception):
                    pass

        # 3. Related KG entities
        if self._semantic:
            keywords = self._extract_keywords(current_message)
            if keywords:
                try:
                    entities = await asyncio.wait_for(
                        self._semantic.get_context_for_query(keywords, limit=5),
                        timeout=5,
                    )
                    if entities:
                        kg_text = "Known infrastructure context:\n" + "\n".join(
                            f"- {e.name}: {e.properties}" for e in entities
                        )
                        messages.append(LLMMessage(role="system", content=kg_text))
                except (asyncio.TimeoutError, Exception):
                    pass

        # 3.5 Matching installed skills
        if self._skill_store:
            try:
                matching_skills = await self._skill_store.find_matching_skills(
                    current_message, limit=2
                )
                for skill in matching_skills:
                    if skill.prompt_template:
                        skill_text = (
                            f"## Active Skill: {skill.name}\n"
                            f"{skill.description}\n\n"
                            f"{skill.prompt_template[:3000]}"
                        )
                        messages.append(LLMMessage(role="system", content=skill_text))
            except Exception:
                pass

        # 3.7 Context providers (domain-specific context injection)
        for provider in self._context_providers:
            try:
                extra = await asyncio.wait_for(
                    provider.get_context(session_id, current_message, intent),
                    timeout=5,
                )
                messages.extend(extra)
            except Exception:
                pass

        # 4. Conversation history from working memory
        history = self._working.get_messages(session_id)
        messages.extend(history)

        # 5. Sanitize credentials from all messages before sending to LLM
        messages = self._sanitize_credentials(messages)

        return messages

    @staticmethod
    def _sanitize_credentials(messages: list[LLMMessage]) -> list[LLMMessage]:
        """Remove plaintext credentials from messages.

        Leaves ``credential_ref:xxx`` tokens intact (safe for LLM).
        """
        from breadmind.storage.credential_vault import CredentialVault

        sanitized = []
        for msg in messages:
            if msg.content:
                clean = CredentialVault.sanitize_text(msg.content)
                if clean != msg.content:
                    msg = LLMMessage(role=msg.role, content=clean)
            sanitized.append(msg)
        return sanitized

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

        # Build summary from user messages (sanitize to prevent credential leakage)
        from breadmind.storage.credential_vault import CredentialVault
        user_msgs = [CredentialVault.sanitize_text(m.content) for m in messages if m.role == "user" and m.content]
        if not user_msgs:
            return None

        summary = "Session summary: " + " | ".join(user_msgs[:5])

        # Extract keywords from all messages (sanitize to prevent credential leakage)
        all_text = CredentialVault.sanitize_text(" ".join(m.content for m in messages if m.content))
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

    async def promote_contacts_to_kg(self, contacts: list) -> list[KGEntity]:
        """Promote Contact objects to KGEntity in semantic memory.

        Creates entities of type 'person' with contact info as properties.
        Creates 'works_at' relations for contacts with organizations.
        """
        if not self._semantic:
            return []

        import logging

        entities: list[KGEntity] = []
        for contact in contacts:
            entity_id = f"contact-{contact.id}"

            properties: dict = {"source": "contact"}
            if contact.email:
                properties["email"] = contact.email
            if contact.phone:
                properties["phone"] = contact.phone
            if contact.platform_ids:
                properties["platforms"] = contact.platform_ids

            entity = KGEntity(
                id=entity_id,
                entity_type="person",
                name=contact.name,
                properties=properties,
                weight=1.0,
            )

            try:
                await self._semantic.upsert_entity(entity)
                entities.append(entity)

                # Create org relation if available
                if contact.organization:
                    org_id = f"org-{contact.organization.lower().replace(' ', '-')}"
                    org_entity = KGEntity(
                        id=org_id,
                        entity_type="organization",
                        name=contact.organization,
                        properties={},
                        weight=0.8,
                    )
                    await self._semantic.upsert_entity(org_entity)

                    relation = KGRelation(
                        source_id=entity_id,
                        target_id=org_id,
                        relation_type="works_at",
                        weight=1.0,
                    )
                    await self._semantic.add_relation(relation)

            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Contact KG promotion failed for %s: %s", contact.name, e,
                )

        return entities

    async def auto_promote(self, message_threshold: int = 10, force_session_ids: list[str] | None = None) -> dict:
        """Automatically promote qualifying sessions to episodic, then to semantic.

        Triggers:
        1. Sessions with >= message_threshold messages
        2. Forced sessions (e.g., on session close)
        3. Sessions with high-importance content (explicit memory requests, config changes)

        Returns summary of what was promoted.
        """
        import logging

        promoted = {"episodic_notes": 0, "semantic_entities": 0}

        if not self._working:
            return promoted

        session_ids = list(self._working._sessions.keys())

        for session_id in session_ids:
            session = self._working._sessions.get(session_id)
            if not session:
                continue

            msg_count = len(session.messages)
            should_promote = False

            # Trigger 1: Message count threshold
            if msg_count >= message_threshold:
                should_promote = True

            # Trigger 2: Forced (session close)
            if force_session_ids and session_id in force_session_ids:
                should_promote = True

            # Trigger 3: Importance detection — check for memory-worthy keywords
            if not should_promote and msg_count >= 2:
                should_promote = self._has_important_content(session)

            if should_promote:
                try:
                    note = await self.promote_to_episodic(session_id, message_threshold=1)
                    if note:
                        promoted["episodic_notes"] += 1
                        # Pin notes from important sessions
                        if self._has_important_content(session):
                            self._episodic.pin_note(note)
                except Exception as e:
                    logging.getLogger(__name__).warning(f"Failed to promote session {session_id}: {e}")

        # Phase 2: Promote new episodic notes to semantic
        if promoted["episodic_notes"] > 0 and self._semantic:
            try:
                all_notes = await self._episodic.get_all_notes() if self._episodic else []
                recent = all_notes[-promoted["episodic_notes"]:] if all_notes else []
                if recent:
                    entities = await self.promote_to_semantic(recent)
                    promoted["semantic_entities"] = len(entities) if entities else 0
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to promote to semantic: {e}")

        return promoted

    def _has_important_content(self, session) -> bool:
        """Check if a session contains memory-worthy content even if short."""
        importance_markers = [
            "기억", "remember", "잊지", "don't forget", "항상", "always",
            "설정", "config", "변경", "change", "배포", "deploy",
            "preference", "선호", "default", "기본",
        ]
        for msg in session.messages:
            if msg.content:
                content_lower = msg.content.lower()
                if any(marker in content_lower for marker in importance_markers):
                    return True
        return False
