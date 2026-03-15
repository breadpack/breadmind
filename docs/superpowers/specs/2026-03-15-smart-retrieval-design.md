# Smart Retrieval System Design

**Date:** 2026-03-15
**Status:** Approved (rev.2 — post-review fixes)
**Depends on:** Self-Expansion System (implemented)

## Overview

SkillStore와 TeamBuilder의 skill/context 검색을 RAG + KG 기반으로 교체하여, 현재 작업과 관련된 skill과 정보만 선별적으로 주입한다. 토큰 budget 제한으로 확장 시에도 비용이 통제된다.

## Architecture

```
Query (goal / task description)
    │
    ▼
SmartRetriever
    ├─ EmbeddingService.encode(query)
    │       │
    │  ┌────┴──────────┐    ┌───────────────┐
    │  │ Vector Search │    │ KG Graph Walk │
    │  │ (pgvector /   │    │ (skill↔role   │
    │  │  in-memory)   │    │  ↔tool↔domain)│
    │  └────┬──────────┘    └──────┬────────┘
    │       │                      │
    │       └── merge + rerank ────┘
    │                │
    │       TokenBudget filter
    │                │
    └────────────────┘
             │
             ▼
    ScoredSkill[] + ContextItem[]
```

## Component 1: EmbeddingService

**File:** `src/breadmind/memory/embedding.py`

### Responsibility
텍스트를 벡터로 변환. sentence-transformers 미설치 시 graceful degradation.

### Interface

```python
class EmbeddingService:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2")

    async def encode(self, text: str) -> list[float] | None
    async def encode_batch(self, texts: list[str]) -> list[list[float] | None]
    def cosine_similarity(self, a: list[float], b: list[float]) -> float
    def is_available(self) -> bool
```

### Behavior
- 모델은 lazy 로딩 (첫 `encode()` 호출 시 로드)
- `all-MiniLM-L6-v2`: 384차원, ~80MB, 빠른 인코딩
- `encode()`는 asyncio.to_thread()로 감싸서 블로킹 방지
- sentence-transformers 미설치 시 `is_available() → False`, `encode() → None`
- 인코딩 결과 LRU 캐시 (최대 500개, key는 text의 hash). `encode_batch()`는 내부적으로 개별 캐시 lookup 후 미스만 배치 인코딩.

## Component 2: SmartRetriever

**File:** `src/breadmind/core/smart_retriever.py`

### Responsibility
벡터 유사도 + KG 관계를 결합하여, 토큰 budget 내에서 가장 관련성 높은 skill과 컨텍스트를 반환.

### Data Model

```python
@dataclass
class ScoredSkill:
    skill: Skill
    score: float            # 0.0 ~ 1.0 (merged relevance)
    token_estimate: int     # len(prompt_template) // 4
    source: str             # "vector" | "kg" | "both"

@dataclass
class ContextItem:
    content: str
    score: float
    source: str             # "episodic" | "kg"
    token_estimate: int
```

### Interface

```python
class SmartRetriever:
    def __init__(self, embedding_service: EmbeddingService,
                 episodic_memory: EpisodicMemory,
                 semantic_memory: SemanticMemory,
                 skill_store: SkillStore,
                 db: Database | None = None)

    # Skill retrieval (replaces SkillStore.find_matching_skills)
    async def retrieve_skills(self, query: str, token_budget: int = 2000,
                              limit: int = 5) -> list[ScoredSkill]

    # Context retrieval (past task history)
    async def retrieve_context(self, query: str, token_budget: int = 1000,
                               limit: int = 5) -> list[ContextItem]

    # Indexing (called on skill/task creation)
    async def index_skill(self, skill: Skill)
    async def index_task_result(self, role: str, task_desc: str,
                                result_summary: str, success: bool)
```

### Retrieval Algorithm

`retrieve_skills(query, token_budget)`:

1. **Vector search**: encode query → search EpisodicMemory by embedding similarity → get top 10 skill notes (tag filter: `"skill:*"`) with scores
2. **KG search**: extract keywords from query using `ContextBuilder._extract_keywords()` (reuse existing method) → find matching KG entities → walk relations to find connected skills → score by relation weight × entity weight
3. **Merge**: combine results, dedup by skill name
   - If skill found by both: score = vector_score × 0.6 + kg_score × 0.4
   - If vector only: score = vector_score × 0.6
   - If KG only: score = kg_score × 0.4
4. **Sort** by score descending
5. **Token budget**: accumulate `token_estimate` until budget exceeded, return selected. Candidate list is always < 20 after merge, so O(n) scanning is acceptable.

### Indexing

`index_skill(skill)`:
1. Embed `f"{skill.name}: {skill.description}. {skill.prompt_template[:200]}"` → store in EpisodicMemory with tag `"skill:{name}"`, also store in `embedding_vec` column if pgvector available
2. Create KG entities and relations:
   - Entity: `skill:{name}` (type="skill")
   - Relations from trigger_keywords: `skill:{name} → related_to → domain:{keyword}` for each keyword
   - If role association detectable: `skill:{name} → related_to → role:{role_name}`

`index_task_result(role, task_desc, result_summary, success)`:
1. Embed `f"[{role}] {task_desc}: {result_summary}"` → store in EpisodicMemory with tags `["task_history", f"role:{role}"]`
2. Create/update KG relation: `role:{role} → executed → task:{hash}` with weight = 1.0 if success, 0.3 if failure
3. Task hash: `hashlib.sha256(f"{role}:{task_desc}".encode()).hexdigest()[:12]`

### Fallback Chain
1. Embedding available + pgvector → full vector search via DB
2. Embedding available + no pgvector → in-memory cosine similarity over EpisodicNote.embedding
3. No embedding → keyword matching via EpisodicMemory.search_by_keywords()
4. No EpisodicMemory → SkillStore keyword matching (current behavior)

### Concurrency
- `index_skill()`과 `index_task_result()`는 EpisodicMemory와 SemanticMemory의 mutating 메서드를 호출한다.
- EpisodicMemory.add_note()는 in-memory 모드에서 `self._notes`와 `self._next_id`를 잠금 없이 변경한다 (기존 코드 한계).
- SmartRetriever에 `self._index_lock = asyncio.Lock()`을 추가하여, `index_skill()`과 `index_task_result()` 전체를 직렬화한다. 이는 EpisodicMemory 자체를 수정하지 않고도 안전한 인덱싱을 보장한다.

## Component 3: Database Extensions

**File:** `src/breadmind/storage/database.py` (modify)

### Embedding Column Strategy

기존 `episodic_notes` 테이블에는 `embedding FLOAT8[]` 컬럼이 이미 있다. 이를 유지하면서 pgvector 전용 `embedding_vec vector(384)` 컬럼을 추가한다:
- `embedding FLOAT8[]` — 기존 호환성 유지, EpisodicNote.embedding에 매핑
- `embedding_vec vector(384)` — pgvector 인덱싱/검색 전용

기존 `save_note()` 메서드는 변경하지 않는다. 새 `save_note_with_vector()` 메서드가 `embedding_vec`도 함께 저장한다.

### pgvector Support

```sql
-- Migration (idempotent, wrapped in try/except)
CREATE EXTENSION IF NOT EXISTS vector;

-- Add vector column if not exists
ALTER TABLE episodic_notes
    ADD COLUMN IF NOT EXISTS embedding_vec vector(384);

-- HNSW index (better than IVFFlat for small datasets)
CREATE INDEX IF NOT EXISTS idx_episodic_embedding_hnsw
    ON episodic_notes USING hnsw (embedding_vec vector_cosine_ops);
```

pgvector 마이그레이션은 `try/except`로 감싸서, 권한 부족이나 extension 미설치 시 조용히 스킵하고 in-memory fallback 사용.

### New Methods

```python
async def has_pgvector(self) -> bool
    # SELECT 1 FROM pg_extension WHERE extname = 'vector'

async def save_note_with_vector(self, note: EpisodicNote, embedding: list[float]) -> int
    # INSERT with both embedding (FLOAT8[]) and embedding_vec (vector)

async def search_by_embedding(self, embedding: list[float], limit: int = 5,
                               tag_filter: str | None = None) -> list[tuple[EpisodicNote, float]]
    # Returns (note, similarity_score) pairs
    # SQL: SELECT *, 1 - (embedding_vec <=> $1::vector) as score
    #      FROM episodic_notes
    #      WHERE ($2 IS NULL OR $2 = ANY(tags))
    #      ORDER BY embedding_vec <=> $1::vector
    #      LIMIT $3
```

## Integration Points

### SkillStore Changes
- `add_skill()` → after adding, call `smart_retriever.index_skill(skill)` if retriever available
- `find_matching_skills()` → delegate to `smart_retriever.retrieve_skills()` if retriever available, else fallback to current keyword matching. 반환값은 기존 `list[Skill]` 유지 (ScoredSkill에서 skill만 추출).
- Add `set_retriever(retriever)` setter

### TeamBuilder Changes
- `_find_skill_injections()` → SmartRetriever 사용 시 `retrieve_skills(goal, token_budget=2000)` 호출
- `TeamPlan.skill_injections` 타입은 `dict[str, list[str]]`로 유지. SmartRetriever가 반환한 `ScoredSkill[]`에서 `skill.prompt_template`만 추출하여 기존 형식에 맞춤.
- score > 0.3인 skill만 포함

### SwarmManager Changes
- After task completion (in run_task finally block), call `smart_retriever.index_task_result()` if retriever available
- Add `set_retriever(retriever)` setter

### main.py Changes
- **EpisodicMemory와 SemanticMemory 초기화 추가** (현재 main.py에서 생성되지 않음)
- Initialize EmbeddingService
- Initialize SmartRetriever with all dependencies
- Wire into SkillStore, TeamBuilder, SwarmManager
- Optional: background task for EmbeddingService model preload

### ContextBuilder 관계
- SmartRetriever는 ContextBuilder를 대체하지 않는다. ContextBuilder는 대화 컨텍스트 조합용이고, SmartRetriever는 skill/task 검색 전용이다.
- SmartRetriever는 ContextBuilder의 `_extract_keywords()` 로직을 재사용한다 (import 또는 유틸리티 함수로 추출).

## KG Entity/Relation Conventions

### Entity Types
- `"skill"` — id: `skill:{name}`, properties: {description, source}
- `"domain"` — id: `domain:{keyword}`, properties: {}
- `"role"` — id: `role:{name}`, properties: {} (auto-created when indexing)

### Relation Types
- `skill → related_to → domain` (weight: 1.0)
- `skill → related_to → role` (weight: 1.0)
- `role → executed → task_history_note` (weight: success ? 1.0 : 0.3)

## Token Budget Strategy

Default budgets:
- Skill injection per swarm task: 2000 tokens
- Context (past history) per swarm task: 1000 tokens
- Token estimation: `len(text) // 4` (conservative approximation)

Selection algorithm:
```python
selected = []
used_tokens = 0
for item in sorted_by_score_desc:
    if used_tokens + item.token_estimate > budget:
        continue  # skip, don't break (smaller items may fit)
    selected.append(item)
    used_tokens += item.token_estimate
```

## Concurrency
- EmbeddingService: asyncio.to_thread() for model inference, dict-based cache (key=hash(text))
- SmartRetriever: `_index_lock = asyncio.Lock()` for index_skill/index_task_result serialization
- Database: connection pool handles concurrency

## File Size Estimates
- `memory/embedding.py`: ~120 lines
- `core/smart_retriever.py`: ~280 lines
- Changes to `storage/database.py`: ~50 lines
- Changes to `core/skill_store.py`: ~20 lines
- Changes to `core/team_builder.py`: ~15 lines
- Changes to `core/swarm.py`: ~10 lines
- Changes to `main.py`: ~30 lines
- **Total: ~525 lines new/modified**
