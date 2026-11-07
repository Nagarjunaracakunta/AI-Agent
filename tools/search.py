"""Stub web search for the Researcher agent.

Returns canned results so the crew can run without a search API key.
To go live later, replace the body of `search_web` with a Tavily call
(keep the same return shape) and nothing else needs to change.
"""
import json

from pydantic import BaseModel, Field, ValidationError


class SearchArgs(BaseModel):
    query: str = Field(description="Search query, e.g. 'Kubernetes pod networking'")


def search_web(query: str) -> dict:
    return {
        "note": "STUB results (no real web search). Content is generic.",
        "query": query,
        "results": [
            {
                "title": f"{query}: overview",
                "url": "https://example.com/overview",
                "snippet": f"A high-level introduction to {query}, its purpose and key concepts.",
            },
            {
                "title": f"{query}: how it works",
                "url": "https://example.com/how-it-works",
                "snippet": f"Explains the main components of {query} and how they interact.",
            },
            {
                "title": f"{query}: best practices",
                "url": "https://example.com/best-practices",
                "snippet": f"Common pitfalls and recommended practices when working with {query}.",
            },
        ],
    }


SEARCH_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for facts and sources on a topic.",
            "parameters": SearchArgs.model_json_schema(),
        },
    }
]


def execute_search(name: str, raw_args: str) -> dict:
    """Same contract as tools.execute_tool: never raises."""
    if name != "search_web":
        return {"error": f"Unknown tool '{name}'"}
    try:
        args = SearchArgs(**json.loads(raw_args or "{}"))
    except (json.JSONDecodeError, ValidationError) as e:
        return {"error": f"Invalid arguments: {e}"}
    return search_web(args.query)
