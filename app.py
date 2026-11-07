import logging
import os
import re
import uuid

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from agent import run_agent
from memory.manager import build_manager

load_dotenv()

MODEL = "openai/gpt-4o-mini"
MAX_MEMORY = 10
SYSTEM_PROMPT = (
    "You are a friendly Travel Planner assistant. "
    "Use the provided tools for live data: weather, currency conversion and "
    "flights. Never guess weather or exchange rates. "
    "If details are missing (city, date, currency), ask the user. "
    "Flight results are mock data, so say so. Keep answers concise."
)

st.set_page_config(page_title="Travel Planner", page_icon="✈️")
st.title("✈️ Travel Planner")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)


@st.cache_resource(ttl=60, show_spinner=False)
def get_memory(_client):
    """Connect to Redis + Postgres. If they are down, the app still works
    without cross-session memory. Re-checked every 60s."""
    try:
        return build_manager(_client), None
    except Exception as e:
        logging.getLogger(__name__).exception("Memory backends unavailable")
        # Show the reason, but never credentials from a connection string.
        reason = re.sub(r"://[^@\s]*@", "://***@", str(e))[:120]
        return None, f"{type(e).__name__}: {reason}"


memory, memory_error = get_memory(client)


def build_system_prompt(facts, summaries):
    """System prompt + recalled long-term facts + session summaries."""
    parts = [SYSTEM_PROMPT]
    if facts:
        parts.append(
            "Known facts about this user, from earlier conversations. Use them "
            "naturally when relevant, do not mention them otherwise, and never "
            "invent facts:\n" + "\n".join(f"- {f['fact']}" for f in facts)
        )
    if summaries["current"]:
        parts.append("Summary of the earlier part of this conversation:\n"
                     + summaries["current"])
    if summaries["past"]:
        parts.append("Summaries of previous conversations:\n"
                     + "\n---\n".join(summaries["past"]))
    return "\n\n".join(parts)


# ---- identity: user (owns long-term memory) and session (owns the chat) ----
# Both live in the URL, so a refresh keeps the same user and conversation.
if "user" not in st.query_params:
    st.query_params["user"] = f"user-{uuid.uuid4().hex[:6]}"
if "sid" not in st.query_params:
    st.query_params["sid"] = uuid.uuid4().hex[:12]
user_id = st.query_params["user"]
session_id = st.query_params["sid"]

with st.sidebar:
    new_user = st.text_input(
        "User ID", value=user_id,
        help="Memories are stored per user ID. Use the same ID to be "
             "remembered across sessions and devices.",
    ).strip()
    if new_user and new_user != user_id:
        st.query_params["user"] = new_user
        st.rerun()

    if st.button("➕ New chat", use_container_width=True):
        if memory:
            try:
                memory.close_session(user_id, session_id)  # summarise, then clear
            except Exception as e:
                st.toast(f"Could not save session summary: {e}", icon="⚠️")
        st.query_params["sid"] = uuid.uuid4().hex[:12]
        st.rerun()

# ---- short-term memory: restore this session's chat (Redis) ----
if st.session_state.get("loaded_sid") != session_id:
    turns = []
    if memory:
        try:
            turns = memory.get_turns(session_id)
        except Exception as e:
            st.toast(f"Could not load chat history: {e}", icon="⚠️")
    st.session_state.memory = turns
    st.session_state.loaded_sid = session_id

for message in st.session_state.memory:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about weather, currency or flights..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.memory.append({"role": "user", "content": prompt})

    # 1. RECALL: top-k relevant long-term facts + session summaries
    facts, summaries = [], {"current": None, "past": []}
    if memory:
        try:
            facts = memory.recall(user_id, prompt)
            summaries = memory.context_summaries(user_id, session_id)
        except Exception as e:
            st.toast(f"Memory recall failed: {e}", icon="⚠️")

    # 2. ANSWER (unchanged tool-calling agent, with memory in the system prompt)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            reply, tool_log = run_agent(
                client,
                MODEL,
                [{"role": "system", "content": build_system_prompt(facts, summaries)}]
                + st.session_state.memory[-MAX_MEMORY:],
            )
        if facts:
            with st.expander(f"🧠 Used {len(facts)} memories"):
                for f in facts:
                    st.write(f"- {f['fact']}  _(match {f['similarity']:.2f})_")
        for call in tool_log:
            with st.expander(f"🔧 {call['name']}({call['arguments']})"):
                st.json(call["result"])
        st.markdown(reply)
    st.session_state.memory.append({"role": "assistant", "content": reply})

    # 3. WRITE: buffer the turns, extract + store new facts, summarise if long
    if memory:
        try:
            memory.add_turn(session_id, "user", prompt)
            memory.add_turn(session_id, "assistant", reply)
            memory.remember(user_id, prompt, reply)
            memory.maybe_summarise(user_id, session_id)
        except Exception as e:
            st.toast(f"Could not save to memory: {e}", icon="⚠️")

# ---- privacy: let the user see and delete what is remembered ----
# (rendered last so facts saved during this run show up immediately)
with st.sidebar:
    st.divider()
    st.subheader("🧠 What I remember")
    if memory is None:
        st.caption(
            f"Memory is offline ({memory_error}). Chat works, but nothing is "
            "remembered across sessions. Start Redis and Postgres with "
            "`docker compose up -d`."
        )
    else:
        try:
            stored = memory.list_memories(user_id)
        except Exception as e:
            stored = []
            st.caption(f"Could not load memories: {e}")
        if not stored:
            st.caption("Nothing stored yet. Tell me about your preferences!")
        for m in stored:
            c1, c2 = st.columns([6, 1])
            c1.write(m["fact"])
            if c2.button("🗑️", key=f"del_{m['id']}", help="Forget this"):
                memory.forget(user_id, m["id"])
                st.rerun()
        if stored:
            with st.popover("Forget everything", use_container_width=True):
                st.write("Delete all stored memories and summaries for this user?")
                if st.button("Yes, delete all", type="primary"):
                    memory.forget_all(user_id)
                    st.rerun()
