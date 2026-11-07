"""The small LLM jobs behind memory: extract facts, judge duplicates, summarise."""
import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class Facts(BaseModel):
    facts: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    action: Literal["add", "update", "skip"]
    id: int | None = None


def parse_json(text: str, model):
    """Pull the first {...} block out of an LLM reply and validate it."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return model(**json.loads(text[start:end]))
    except (ValueError, ValidationError):
        return None


def _chat(client, model: str, system: str, user: str) -> str:
    response = client.chat.completions.create(
        model=model, temperature=0,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
    )
    return response.choices[0].message.content or ""


EXTRACT_SYSTEM = (
    "You extract durable facts about the USER from one chat exchange so an "
    "assistant can remember them later. Keep only stable facts and "
    "preferences: name, location, job, favourite tools, travel preferences, "
    "goals, constraints. Skip small talk, questions, one-off requests (such "
    "as a single weather lookup) and anything about the assistant. Write each "
    "fact as a short sentence starting with 'User', e.g. \"User's name is "
    "Arjun\". At most 5 facts. Return ONLY JSON: {\"facts\": [\"...\"]}, "
    "with an empty list if there is nothing worth remembering."
)


def extract_facts(client, model: str, user_msg: str, assistant_msg: str) -> list[str]:
    reply = _chat(client, model, EXTRACT_SYSTEM,
                  f"User said: {user_msg}\n\nAssistant replied: {assistant_msg}")
    parsed = parse_json(reply, Facts)
    if not parsed:
        return []
    seen, facts = set(), []
    for f in parsed.facts:
        f = f.strip()
        if f and f.lower() not in seen:
            seen.add(f.lower())
            facts.append(f)
    return facts[:5]


DECIDE_SYSTEM = (
    "You maintain a user's long-term memory and keep it free of duplicates. "
    "Given a NEW fact and similar EXISTING memories, decide: "
    "'skip' if the new fact is already covered; "
    "'update' (with the id of the memory to replace) if it refines, corrects "
    "or contradicts an existing memory, such as a changed location or "
    "preference; 'add' if it is genuinely new information. "
    "Return ONLY JSON: {\"action\": \"add|update|skip\", \"id\": <existing id or null>}"
)


def decide(client, model: str, new_fact: str, candidates: list[dict]) -> Decision:
    existing = "\n".join(f"[{c['id']}] {c['fact']}" for c in candidates)
    reply = _chat(client, model, DECIDE_SYSTEM,
                  f"NEW fact: {new_fact}\n\nEXISTING memories:\n{existing}")
    parsed = parse_json(reply, Decision)
    valid_ids = {c["id"] for c in candidates}
    if not parsed or (parsed.action == "update" and parsed.id not in valid_ids):
        return Decision(action="add")  # when unsure, keep the information
    return parsed


SUMMARISE_SYSTEM = (
    "You summarise a chat so an assistant can continue it later. Write a "
    "compact summary (max 120 words) of what the user wanted, decisions made "
    "and any open questions. Keep names, places, dates and preferences. "
    "Return only the summary text."
)


def summarise(client, model: str, previous_summary: str | None, turns: list[dict]) -> str:
    transcript = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
    prior = f"Earlier summary:\n{previous_summary}\n\n" if previous_summary else ""
    return _chat(client, model, SUMMARISE_SYSTEM,
                 f"{prior}New conversation to fold in:\n{transcript}").strip()
