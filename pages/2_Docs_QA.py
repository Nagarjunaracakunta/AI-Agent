import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from rag.agent import build_rag_graph, extract_citations, initial_state
from rag.config import DEFAULT_COLLECTION, MAX_RETRIES
from rag.store import RagStore

load_dotenv()

st.set_page_config(page_title="Docs Q&A", page_icon="📚")
st.title("📚 Docs Q&A")
st.caption("Ask questions about the indexed documents. Answers cite their sources "
           "and are checked against them. No citation means no answer.")

client = OpenAI(base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY"))


@st.cache_resource(ttl=60, show_spinner=False)
def get_store():
    try:
        return RagStore(), None
    except Exception as e:
        return None, f"{type(e).__name__}"


store, store_error = get_store()
if store is None:
    st.error(f"The document index is unavailable ({store_error}). Check the "
             "DATABASE_URL secret, or run `docker compose up -d` locally.")
    st.stop()

docs = store.list_documents(DEFAULT_COLLECTION)

with st.sidebar:
    st.subheader("📄 Indexed documents")
    if not docs:
        st.caption("Nothing indexed yet. Run:\n\n`python -m rag.ingest docs/`")
    for d in docs:
        st.write(f"**{d['source']}**  \n{d['chunks']} chunks")
    if docs:
        st.caption(f"Last indexed: {max(d['ingested_at'] for d in docs):%Y-%m-%d %H:%M} UTC")
    if st.button("Clear chat", use_container_width=True):
        st.session_state.rag_messages = []
        st.rerun()

if "rag_messages" not in st.session_state:
    st.session_state.rag_messages = []


def render_sources(sources):
    if not sources:
        return
    with st.expander(f"📎 Sources ({len(sources)})"):
        for s in sources:
            where = f"{s['source']}" + (f", page {s['page']}" if s.get("page") else "")
            st.markdown(f"**`[{s['key']}]`** {where}" +
                        (f"  \n_{s['heading']}_" if s.get("heading") else ""))
            st.code(s["text"], language=None, wrap_lines=True)


def render_answer(text, cited):
    for key in cited:  # make citations stand out
        text = text.replace(f"[{key}]", f"`[{key}]`")
    st.markdown(text)


for m in st.session_state.rag_messages:
    with st.chat_message(m["role"]):
        if m["role"] == "assistant":
            render_answer(m["content"], m.get("cited", []))
            if m.get("warning"):
                st.warning(m["warning"])
            render_sources(m.get("sources"))
        else:
            st.markdown(m["content"])

if not docs:
    st.info("Index some documents first (see the sidebar), then ask a question.")
    st.stop()

if question := st.chat_input("Ask about the runbooks, e.g. 'What does error TLS-1042 mean?'"):
    with st.chat_message("user"):
        st.markdown(question)
    history = [{"role": m["role"], "content": m["content"]}
               for m in st.session_state.rag_messages]
    st.session_state.rag_messages.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        final, seen = {}, 0
        try:
            graph = build_rag_graph(client, store, DEFAULT_COLLECTION)
            with st.status("Searching the documents...", expanded=True) as status:
                for state in graph.stream(initial_state(question, history),
                                          stream_mode="values"):
                    final = state
                    for t in state["trace"][seen:]:
                        if t["step"] == "search":
                            kept = ", ".join(f"`{k}` ({s:g})" for k, s in t["kept"]) or "nothing relevant"
                            st.write(f"🔎 Searched **{t['query']}** → {kept}")
                        elif t["step"] == "answer":
                            st.write(f"✍️ Drafted an answer (attempt {t['attempt']})")
                        elif t["step"] == "verify":
                            if t["grounded"]:
                                st.write("✅ Checked against the sources")
                            else:
                                st.write("⚠️ Check failed, retrying: " + "; ".join(t["issues"][:2]))
                    seen = len(state["trace"])
                status.update(label="Done", state="complete", expanded=False)
        except Exception as e:
            st.error(f"Something went wrong: {e}")
            st.stop()

        answer, cited = final["answer"], final.get("cited", [])
        sources = [{"key": k, **{f: final["evidence"][k].get(f) for f in
                                 ("source", "page", "heading", "text")}} for k in cited]
        warning = None
        if not final["refused"] and not final["grounded"]:
            warning = ("I couldn't fully verify this answer against the sources: "
                       + "; ".join(final["issues"][:2]) + " Please check the cited passages.")

        render_answer(answer, cited)
        if warning:
            st.warning(warning)
        render_sources(sources)
        searches = sum(1 for t in final["trace"] if t["step"] == "search")
        st.caption(f"{final['tokens']:,} tokens · {searches} search(es) · "
                   f"{final['attempt']} attempt(s)")

    st.session_state.rag_messages.append({
        "role": "assistant", "content": answer, "cited": cited,
        "sources": sources, "warning": warning})
