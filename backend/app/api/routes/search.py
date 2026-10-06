from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core import rate_limit
from app.db.database import get_db
from app.db.models import User
from app.rag.retrieval import query_vector, search_knowledge, search_user_documents

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    scope: Literal["documents", "knowledge", "all"] = "all"
    limit: int = Field(default=5, ge=1, le=10)


class SearchHit(BaseModel):
    source_type: Literal["user_document", "knowledge_base"]
    text: str
    score: float
    title: str
    section: str | None
    page: int | None
    document_id: str | None
    document_type: str | None
    source: str | None
    category: str | None


@router.post("", response_model=list[SearchHit],
             summary="Search your documents and/or the travel policy knowledge base")
async def search(body: SearchRequest, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    await rate_limit.enforce("search", str(user.id), 60, 60)
    vector = await query_vector(body.query)  # embed once for both scopes
    hits = []
    if body.scope in ("documents", "all"):
        hits += await search_user_documents(db, user.id, body.query, body.limit, vector)
    if body.scope in ("knowledge", "all"):
        hits += await search_knowledge(db, body.query, body.limit, vector)
    return [SearchHit(**asdict(h)) for h in hits]
