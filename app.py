import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = "openai/gpt-4o-mini"
SYSTEM_PROMPT = "You are a helpful assistant."

st.set_page_config(page_title="OpenRouter Chatbot", page_icon="💬")
st.title("💬 OpenRouter Chatbot")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

if prompt := st.chat_input("Type your message..."):
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        st.markdown(response.choices[0].message.content)
