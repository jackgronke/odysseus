from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from . import db
from .embeddings import (
    EmbeddingProvider,
    build_embedding_provider,
    index_memory_item,
)
from .memory_candidates import (
    AGENT_MEMORY_TYPES,
    ALLOWED_STATUSES,
    ASSISTANT_HIGH_AUTHORITY_STATUSES,
    ASSISTANT_RESTRICTED_FACT_TYPES,
    MemoryCandidateParseResult,
    parse_memory_candidates,
)
from .vector_index import VectorIndex, build_vector_index


@dataclass(frozen=True)
class MemoryCandidateExtractionResult:
    episode_id: int
    status: str
    valid_count: int
    rejected_count: int
    candidates: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    malformed: bool = False
    error: str | None = None
    raw_output: str | None = None


@dataclass(frozen=True)
class MemoryCandidateStoreResult:
    created_count: int
    indexed_count: int
    created_memory_item_ids: list[int]
    rejected: list[dict[str, Any]]
    indexing_results: list[dict[str, Any]]


async def extract_memory_candidates_for_episode(
    config: dict[str, Any],
    model: Any,
    episode_id: int,
) -> MemoryCandidateExtractionResult:
    episode = db.get_episode(config, episode_id)
    if episode is None:
        return MemoryCandidateExtractionResult(
            episode_id=episode_id,
            status="no_episode",
            valid_count=0,
            rejected_count=0,
            candidates=[],
            rejected=[],
        )

    distillation_cfg = config.get("maintenance", {}).get("memory_distillation", {})
    max_candidates = int(distillation_cfg.get("max_candidates", 8))
    response = await model.chat(
        [
            {
                "role": "system",
                "content": (
                    "You are running an Anchor maintenance turn. Extract candidate "
                    "memory_items from one existing episode. Return JSON only. Do not "
                    "call tools. Do not create durable memory_items."
                ),
            },
            {
                "role": "user",
                "content": _build_distillation_prompt(episode, max_candidates=max_candidates),
            },
        ],
        temperature=0.1,
        max_tokens=2048,
        tools=None,
    )
    raw_output = _extract_assistant_content(response)
    parsed = parse_memory_candidates(raw_output)
    return _extraction_result(episode_id, parsed, raw_output)


def store_validated_memory_candidates(
    config: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    source_episode_id: int | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_index: VectorIndex | None = None,
) -> MemoryCandidateStoreResult:
    created_ids: list[int] = []
    rejected: list[dict[str, Any]] = []
    indexing_results: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        reasons = _storage_rejection_reasons(config, candidate, source_episode_id)
        if reasons:
            rejected.append({"index": index, "reasons": reasons, "raw": candidate})
            continue
        item_id = db.create_memory_item(
            config,
            type=str(candidate["type"]),
            status=str(candidate["status"]),
            content=str(candidate["content"]),
            summary=str(candidate["summary"]),
            confidence=float(candidate["confidence"]),
            importance=float(candidate["importance"]),
            reinforcement_count=1 if candidate["status"] == "reinforced" else 0,
            source_episode_id=_source_episode_id(candidate, source_episode_id),
            source_message_id=candidate.get("source_message_id"),
            supersedes_id=candidate.get("supersedes_id"),
            metadata={
                "rationale": candidate.get("rationale"),
                "source_role": candidate.get("source_role"),
                "grounding_roles": candidate.get("grounding_roles") or [],
            },
        )
        event_type = _memory_event_type(candidate)
        event_source = (
            "assistant_memory_distillation"
            if _is_assistant_derived(candidate)
            else "memory_distillation"
        )
        db.record_memory_event(
            config,
            memory_item_id=item_id,
            event_type=event_type,
            source=event_source,
            source_episode_id=_source_episode_id(candidate, source_episode_id),
            source_message_id=candidate.get("source_message_id"),
            note=str(candidate.get("rationale") or ""),
            after={**candidate, "memory_item_id": item_id},
        )
        created_ids.append(item_id)
        indexing_results.append(
            _index_memory_item_after_distillation(
                config,
                memory_item_id=item_id,
                embedding_provider=embedding_provider,
                vector_index=vector_index,
            )
        )
    return MemoryCandidateStoreResult(
        created_count=len(created_ids),
        indexed_count=sum(1 for result in indexing_results if result["ok"]),
        created_memory_item_ids=created_ids,
        rejected=rejected,
        indexing_results=indexing_results,
    )


def _build_distillation_prompt(episode: dict[str, Any], *, max_candidates: int) -> str:
    return (
        "Extract at most "
        f"{max_candidates} candidate memory items from this episode.\n\n"
        "Contract:\n"
        "- Allowed types: user_preference, project_fact, operational_rule, self_model, "
        "relationship, technical_context, unresolved_question, correction, "
        "agent_self_observation, agent_design_hypothesis, agent_improvement_proposal, "
        "agent_behavior_preference.\n"
        "- Allowed statuses: observed, inferred, proposed, reinforced, durable, rejected, "
        "superseded. Never use protected or promoted.\n"
        "- Assistant-derived self/design candidates must use agent_* types, source_role=assistant, "
        "and status=proposed.\n"
        "- Assistant-only candidates must not create user_preference or project_fact unless "
        "grounding_roles includes user or tool evidence from the same episode.\n"
        "- Do not mark assistant-derived candidates durable/reinforced because they were merely "
        "retrieved or stated by the assistant once.\n"
        "- Every candidate needs source_episode_id and/or source_message_id.\n"
        "- Include source_role and grounding_roles.\n"
        "- Include confidence and importance from 0.0 to 1.0.\n"
        "- Do not include secrets, credentials, identity-file changes, tool-policy changes, "
        "or safety-boundary changes as durable memory.\n"
        "- Return strict JSON with a candidates array. No prose.\n\n"
        "Candidate fields: type, status, content, summary, confidence, importance, "
        "source_episode_id, source_message_id, supersedes_id, source_role, "
        "grounding_roles, rationale.\n\n"
        f"Episode id: {episode['id']}\n"
        f"Source messages: {episode['source_start_message_id']}..{episode['source_end_message_id']}\n"
        f"Summary:\n{episode['summary']}"
    )


def _storage_rejection_reasons(
    config: dict[str, Any],
    candidate: dict[str, Any],
    source_episode_id: int | None,
) -> list[str]:
    reasons: list[str] = []
    status = candidate.get("status")
    if status not in ALLOWED_STATUSES:
        reasons.append("disallowed_status")
    if _is_assistant_derived(candidate):
        if candidate.get("type") in AGENT_MEMORY_TYPES and status != "proposed":
            reasons.append("assistant_agent_memory_must_be_proposed")
        if status in ASSISTANT_HIGH_AUTHORITY_STATUSES:
            reasons.append("assistant_disallowed_status")
        if (
            candidate.get("type") in ASSISTANT_RESTRICTED_FACT_TYPES
            and not _has_external_grounding(candidate)
        ):
            reasons.append("assistant_candidate_requires_user_or_tool_grounding")
    if candidate.get("type") in AGENT_MEMORY_TYPES and candidate.get("source_role") != "assistant":
        reasons.append("agent_memory_requires_assistant_source")
    if candidate.get("source_episode_id") is None and candidate.get("source_message_id") is None and source_episode_id is None:
        reasons.append("missing_provenance")
    if status == "reinforced" and not _existing_supersedes_target(config, candidate.get("supersedes_id")):
        reasons.append("reinforced_without_existing_target")
    if _sensitive_boundary_change(str(candidate.get("content") or "")) and candidate.get("type") not in {"unresolved_question", "correction"}:
        reasons.append("sensitive_boundary_change")
    return reasons


def _source_episode_id(candidate: dict[str, Any], fallback: int | None) -> int | None:
    value = candidate.get("source_episode_id")
    return value if isinstance(value, int) else fallback


def _existing_supersedes_target(config: dict[str, Any], value: Any) -> bool:
    if not isinstance(value, int):
        return False
    return db.get_row(config, "memory_items", value) is not None


def _sensitive_boundary_change(content: str) -> bool:
    lowered = content.lower()
    sensitive_terms = ("identity file", "tool policy", "safety boundary", "autonomy boundary")
    change_terms = ("change", "modify", "update", "rewrite", "replace")
    return any(term in lowered for term in sensitive_terms) and any(
        term in lowered for term in change_terms
    )


def _is_assistant_derived(candidate: dict[str, Any]) -> bool:
    return candidate.get("source_role") == "assistant" or candidate.get("type") in AGENT_MEMORY_TYPES


def _has_external_grounding(candidate: dict[str, Any]) -> bool:
    roles = candidate.get("grounding_roles")
    if not isinstance(roles, list):
        return False
    return any(role in {"user", "tool"} for role in roles)


def _memory_event_type(candidate: dict[str, Any]) -> str:
    if _is_assistant_derived(candidate) and candidate.get("status") == "proposed":
        return "proposed"
    return "created"


def _index_memory_item_after_distillation(
    config: dict[str, Any],
    *,
    memory_item_id: int,
    embedding_provider: EmbeddingProvider | None,
    vector_index: VectorIndex | None,
) -> dict[str, Any]:
    embeddings_cfg = config.get("embeddings", {})
    if not bool(embeddings_cfg.get("index_memory_items", True)):
        return {
            "ok": False,
            "status": "memory_item_indexing_disabled",
            "memory_item_id": memory_item_id,
            "embedding_id": None,
            "collection": None,
            "vector_id": None,
            "error": None,
        }
    try:
        result = index_memory_item(
            config,
            memory_item_id=memory_item_id,
            embedding_provider=embedding_provider or build_embedding_provider(config),
            vector_index=vector_index or build_vector_index(config),
        )
        return {
            "ok": result.ok,
            "status": result.status,
            "memory_item_id": memory_item_id,
            "embedding_id": result.embedding_id,
            "collection": result.collection,
            "vector_id": result.vector_id,
            "error": result.error,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "indexing_error",
            "memory_item_id": memory_item_id,
            "embedding_id": None,
            "collection": None,
            "vector_id": None,
            "error": str(exc),
        }


def _extraction_result(
    episode_id: int,
    parsed: MemoryCandidateParseResult,
    raw_output: str,
) -> MemoryCandidateExtractionResult:
    rejected = [
        {
            "index": item.index,
            "reasons": item.reasons,
            "raw": item.raw,
        }
        for item in parsed.rejected
    ]
    candidates = [asdict(candidate) for candidate in parsed.candidates]
    if parsed.malformed:
        return MemoryCandidateExtractionResult(
            episode_id=episode_id,
            status="malformed_json",
            valid_count=0,
            rejected_count=0,
            candidates=[],
            rejected=[],
            malformed=True,
            error=parsed.error,
            raw_output=raw_output,
        )
    return MemoryCandidateExtractionResult(
        episode_id=episode_id,
        status="validated",
        valid_count=len(candidates),
        rejected_count=len(rejected),
        candidates=candidates,
        rejected=rejected,
        raw_output=raw_output,
    )


def _extract_assistant_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""
