import json
from concurrent.futures import ThreadPoolExecutor

from tools import TOOL_SCHEMAS, execute_tool

MAX_STEPS = 5


def run_agent(client, model, messages, max_steps=MAX_STEPS,
              tool_schemas=TOOL_SCHEMAS, executor=execute_tool, usage=None,
              temperature=None):
    """Return (reply_text, tool_log). `messages` is a working copy, so the
    tool messages don't need to be stored in the chat memory.

    tool_schemas / executor let other agents use their own tools (pass
    tool_schemas=None for a tool-free agent). `usage`, if given, is a dict
    whose "total" key accumulates token usage. `temperature` is only sent when set."""
    messages = list(messages)
    tool_log = []

    for _ in range(max_steps):
        kwargs = {"model": model, "messages": messages}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = client.chat.completions.create(**kwargs)
        if usage is not None and getattr(response, "usage", None):
            usage["total"] = usage.get("total", 0) + (response.usage.total_tokens or 0)
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
                lambda tc: executor(tc.function.name, tc.function.arguments),
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
