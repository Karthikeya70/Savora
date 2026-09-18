"""
Thin OpenRouter client. Isolated behind `ask_llm` / `ask_llm_with_tools` so the
rest of the app never touches HTTP details, and so it degrades gracefully (a
clear stub message, not a crash) when no API key is configured.
"""
import json
import os

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

NOT_CONFIGURED_MSG = (
    "[LLM not configured] Set OPENROUTER_API_KEY to enable answers to "
    "open-ended questions. Structured menu questions (allergens, diet, "
    "spice, price, category) still work without it."
)


def llm_configured() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def _post(messages: list, tools: list | None = None, tool_choice: str | None = None, max_tokens: int = 600):
    api_key = os.environ.get("OPENROUTER_API_KEY")
    body = {"model": DEFAULT_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.4}
    if tools:
        body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.Timeout:
        return None, "[LLM error] OpenRouter request timed out. Please try again."
    except requests.exceptions.HTTPError:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            pass
        if resp.status_code == 401:
            return None, "[LLM error] OpenRouter rejected the API key (401). Check OPENROUTER_API_KEY in .env."
        if resp.status_code == 429:
            return None, "[LLM error] OpenRouter rate limit hit (429). Try again shortly."
        return None, f"[LLM error] OpenRouter request failed ({resp.status_code}). {detail}".strip()
    except requests.exceptions.RequestException as e:
        return None, f"[LLM error] Could not reach OpenRouter: {e}"


def ask_llm(system_prompt: str, user_prompt: str, history: list[dict] | None = None, max_tokens: int = 500) -> str:
    if not llm_configured():
        return NOT_CONFIGURED_MSG

    messages = [{"role": "system", "content": system_prompt}]
    for turn in (history or []):
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_prompt})

    data, err = _post(messages, max_tokens=max_tokens)
    if err:
        return err
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return "[LLM error] Unexpected response shape from OpenRouter."


def ask_llm_with_tools(system_prompt: str, user_prompt: str, tools: list, dispatch: dict,
                        history: list[dict] | None = None, max_tokens: int = 600, max_rounds: int = 4) -> tuple[str, list]:
    """Like ask_llm, but lets the model call real functions (tools/dispatch) when needed.
    The caller pre-loads relevant dish context into system_prompt, so the model can
    answer most queries in a single call without any tool use. Tools remain available
    for cases that need precise filtering or full ingredient details.
    Returns (answer_text, tool_calls_made)."""
    if not llm_configured():
        return NOT_CONFIGURED_MSG, []

    messages = [{"role": "system", "content": system_prompt}]
    for turn in (history or []):
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_prompt})

    calls_made = []
    for round_num in range(max_rounds):
        # Always "auto" — anti-hallucination protection now comes from the
        # retrieved context injected into the system prompt, not from forcing
        # a tool call. The model uses tools only when context is insufficient.
        tool_choice = "auto"
        data, err = _post(messages, tools=tools, tool_choice=tool_choice, max_tokens=max_tokens)
        if err:
            return err, calls_made
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError):
            return "[LLM error] Unexpected response shape from OpenRouter.", calls_made

        tool_calls = choice.get("tool_calls")
        if not tool_calls:
            return (choice.get("content") or "").strip(), calls_made

        messages.append(choice)
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                fn_args = {}
            fn = dispatch.get(fn_name)
            result = fn(**fn_args) if fn else {"error": f"unknown tool {fn_name}"}
            calls_made.append({"name": fn_name, "args": fn_args})
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result),
            })

    return "[LLM error] Gave up after too many tool-call rounds.", calls_made
