import json
from concurrent.futures import ThreadPoolExecutor

from tools import TOOL_SCHEMAS, execute_tool

MAX_STEPS = 5


def run_agent(client, model, messages, max_steps=MAX_STEPS):
    """Return (reply_text, tool_log). `messages` is a working copy, so the
    tool messages don't need to be stored in the chat memory."""
    messages = list(messages)
    tool_log = []

    for _ in range(max_steps):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=TOOL_SCHEMAS
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content, tool_log

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name,
                                 "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Run all requested tools in parallel
        with ThreadPoolExecutor() as pool:
            results = list(pool.map(
                lambda tc: execute_tool(tc.function.name, tc.function.arguments),
                msg.tool_calls,
            ))

        for tc, result in zip(msg.tool_calls, results):
            tool_log.append({"name": tc.function.name,
                             "arguments": tc.function.arguments,
                             "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return "Sorry, I couldn't finish that request (too many tool steps).", tool_log
