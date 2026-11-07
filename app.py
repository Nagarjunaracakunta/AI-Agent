import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from agent import run_agent

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

if "memory" not in st.session_state:
    st.session_state.memory = []

for message in st.session_state.memory:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about weather, currency or flights..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.memory.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            reply, tool_log = run_agent(
                client,
                MODEL,
                [{"role": "system", "content": SYSTEM_PROMPT}]
                + st.session_state.memory[-MAX_MEMORY:],
            )
        for call in tool_log:
            with st.expander(f"🔧 {call['name']}({call['arguments']})"):
                st.json(call["result"])
        st.markdown(reply)
    st.session_state.memory.append({"role": "assistant", "content": reply})
