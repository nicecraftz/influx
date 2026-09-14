"""Question -> answer, grounded in the organization's crawled content.

One question, one answer, no conversation: each request is embedded, matched
against the organization's chunks and answered by the generative model from
those passages alone, citing them as [n]. Every answer is logged as a Question
row for the metrics endpoint.
"""

from time import perf_counter

import httpx
from ollama import AsyncClient, ResponseError
from sqlmodel.ext.asyncio.session import AsyncSession

from influx.core.config import ANSWER_CONTEXT_TOKENS, ANSWER_TEMPERATURE, OLLAMA_ANSWER_MODEL, OLLAMA_HOST
from influx.core.logging import get_logger
from influx.organization.domain.models import Organization
from influx.organization.exceptions import OrganizationInactive, OrganizationNotFound
from influx.retrieval.application.search_service import Passage, search_passages
from influx.retrieval.domain.models import Question
from influx.retrieval.exceptions import AnswerUnavailable, NothingIndexed

log = get_logger(__name__)

_client = AsyncClient(host=OLLAMA_HOST)

SYSTEM_PROMPT = """\
You answer questions about an organization using only the numbered passages \
taken from its website. Rules:
- Answer in the language of the question.
- Use only what the passages say. If they do not contain the answer, say so \
plainly and do not guess or use outside knowledge.
- After each statement, cite the passages it comes from as [n].
- Be concise and factual. No preamble, no closing remarks."""


async def answer_question(
    session: AsyncSession, organization_id: int, user_id: int, question: str
) -> tuple[Question, list[Passage]]:
    """Answer `question` from the organization's content and log it.

    Raises OrganizationNotFound / OrganizationInactive, NothingIndexed when
    the organization has no embedded chunks, AnswerUnavailable when Ollama
    cannot be reached or refuses (model not pulled, ...).
    """
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise OrganizationNotFound(f"no organization with id {organization_id}")
    if not organization.active:
        raise OrganizationInactive(f"organization {organization_id} is inactive")

    started = perf_counter()
    try:
        passages = await search_passages(session, organization_id, question)
        if not passages:
            raise NothingIndexed(f"organization {organization_id} has no embedded content yet")
        answer = await generate_answer(question, passages)
    except (ResponseError, httpx.HTTPError) as exc:
        log.error("answering failed for organization %d: %s", organization_id, exc)
        raise AnswerUnavailable(str(exc)) from exc
    latency_ms = int((perf_counter() - started) * 1000)

    logged = Question(
        text=question,
        answer=answer,
        top_similarity=passages[0].similarity,
        passages=len(passages),
        latency_ms=latency_ms,
        organization_id=organization_id,
        user_id=user_id,
    )
    session.add(logged)
    await session.commit()
    log.info(
        "organization %d answered in %d ms (best similarity %.2f, %d passages)",
        organization_id, latency_ms, passages[0].similarity, len(passages),
    )
    return logged, passages


async def generate_answer(question: str, passages: list[Passage]) -> str:
    response = await _client.chat(
        model=OLLAMA_ANSWER_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(question, passages)},
        ],
        # qwen3 "thinks" before answering unless told not to: slower, and the
        # reasoning would land in the answer for models that don't separate it.
        think=False,
        options={"temperature": ANSWER_TEMPERATURE, "num_ctx": ANSWER_CONTEXT_TOKENS},
    )
    return (response.message.content or "").strip()


def build_prompt(question: str, passages: list[Passage]) -> str:
    blocks = [
        f"[{index}] {passage.title or passage.url}\n{passage.url}\n{passage.content}"
        for index, passage in enumerate(passages, start=1)
    ]
    return "Passages:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"
