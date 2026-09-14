from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import select

from influx.auth.dependencies import get_current_user, require_membership
from influx.core.db import SessionDep
from influx.core.time import utcnow
from influx.organization.domain.models import Participation
from influx.retrieval.application.answer_service import answer_question
from influx.retrieval.domain.models import Question
from influx.retrieval.schemas import AnswerRead, MetricsRead, QuestionRequest, SourceRead

retrieval = APIRouter(prefix="/retrieval", tags=["retrieval"], dependencies=[Depends(get_current_user)])

OrganizationMember = Annotated[Participation, Depends(require_membership(param="organization_id"))]


@retrieval.post("/organizations/{organization_id}", response_model=AnswerRead)
async def ask(organization_id: int, body: QuestionRequest, membership: OrganizationMember, session: SessionDep):
    question, passages = await answer_question(session, organization_id, membership.user_id, body.question)
    return AnswerRead(
        id=question.id,
        question=question.text,
        answer=question.answer,
        sources=[
            SourceRead(index=index, url=p.url, title=p.title, similarity=p.similarity, excerpt=p.content)
            for index, p in enumerate(passages, start=1)
        ],
        latency_ms=question.latency_ms,
    )


@retrieval.get("/organizations/{organization_id}/metrics", response_model=MetricsRead)
async def metrics(organization_id: int, membership: OrganizationMember, session: SessionDep):
    since = utcnow() - timedelta(hours=24)
    row = (
        await session.exec(
            select(
                func.count(Question.id),
                func.count(Question.id).filter(Question.created_at >= since),
                func.avg(Question.latency_ms),
                func.avg(Question.top_similarity),
                func.max(Question.created_at),
            ).where(Question.organization_id == organization_id)
        )
    ).one()
    questions, last_24h, latency, similarity, last_at = row
    return MetricsRead(
        questions=questions,
        questions_last_24h=last_24h,
        average_latency_ms=latency,
        average_top_similarity=similarity,
        last_question_at=last_at,
    )
