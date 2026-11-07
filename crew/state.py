import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


class ReviewResult(BaseModel):
    score: int = Field(ge=1, le=10)
    issues: list[str] = Field(default_factory=list)


class SeoResult(BaseModel):
    title: str
    meta_description: str
    hashtags: list[str]


class CrewState(TypedDict, total=False):
    """Shared state / scratchpad. Each agent reads what it needs and
    writes only its own fields."""
    topic: str
    outline: str
    research: str
    draft: str
    score: int
    issues: list[str]
    revision_count: int
    seo: dict
    # `operator.add` makes each node's log entries append instead of overwrite
    log: Annotated[list, operator.add]
