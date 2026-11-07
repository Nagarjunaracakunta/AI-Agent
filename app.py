import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = "openai/gpt-4o-mini"
SYSTEM_PROMPT = (
    "You are a friendly AI tutor. "
    "Adapt explanations to the user's level (beginner, intermediate or expert). "
    "Keep answers concise and use examples. "
    "If you don't know something, say so instead of guessing."
)
MAX_MEMORY = 10  # how many recent messages are sent to the model

st.set_page_config(page_title="OpenRouter Chatbot", page_icon="💬")
st.title("💬 OpenRouter Chatbot")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# Memory: a simple list of {"role", "content"} messages.
# Streamlit re-runs this script on every interaction, so the list lives in
# session_state to survive between messages.
if "memory" not in st.session_state:
    st.session_state.memory = []

# Show the conversation so far
for message in st.session_state.memory:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Type your message..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.memory.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}]
            + st.session_state.memory[-MAX_MEMORY:],
        )
        reply = response.choices[0].message.content
        st.markdown(reply)
    st.session_state.memory.append({"role": "assistant", "content": reply})
