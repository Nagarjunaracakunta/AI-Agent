import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from crew.graph import MAX_REVISIONS, PASS_SCORE, build_graph, initial_state, to_markdown

load_dotenv()

st.set_page_config(page_title="Content Crew", page_icon="📝")
st.title("📝 Content Crew")
st.caption(
    "Planner → Researcher → Writer → Reviewer (revises if score < "
    f"{PASS_SCORE}, max {MAX_REVISIONS} retries) → SEO. "
    "Search is a stub, so research content is generic."
)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

topic = st.text_input("Blog topic", placeholder="K8s networking")

if st.button("Generate blog", type="primary", disabled=not topic.strip()):
    st.session_state.pop("crew_result", None)
    try:
        graph = build_graph(client)
        final, seen = {}, 0
        with st.status("Crew is working...", expanded=True) as status:
            # stream_mode="values" yields the full shared state after each step
            for state in graph.stream(initial_state(topic.strip()), stream_mode="values"):
                final = state
                for e in state["log"][seen:]:
                    st.write(f"✅ **{e['agent']}** finished "
                             f"({e['seconds']}s, {e['tokens']} tokens)")
                seen = len(state["log"])
            status.update(label="Done", state="complete", expanded=False)
        st.session_state.crew_result = final
    except Exception as e:
        st.error(f"Crew failed: {e}")

result = st.session_state.get("crew_result")
if result:
    total_tokens = sum(e["tokens"] for e in result["log"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Final review score", result["score"])
    c2.metric("Revisions", result["revision_count"])
    c3.metric("Total tokens", total_tokens)

    markdown = to_markdown(result)
    st.download_button("Download blog.md", markdown, file_name="blog.md")
    st.markdown(markdown)

    st.subheader("Agent log")
    for e in result["log"]:
        tools = f", tools: {', '.join(e['tool_calls'])}" if e["tool_calls"] else ""
        with st.expander(f"{e['agent']} ({e['seconds']}s, {e['tokens']} tokens{tools})"):
            st.markdown(e["output"])
