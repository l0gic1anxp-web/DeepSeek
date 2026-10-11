import re

_REASONING_RE = re.compile(
    r"<think(?:ing)?>(.*?)</think(?:ing)?>",
    re.DOTALL | re.IGNORECASE,
)


def md_to_html(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    text = re.sub(
        r"```(\w+)?\n(.*?)```",
        lambda m: (
            f'<pre><code class="language-{m.group(1) or "text"}">'
            f"{m.group(2)}</code></pre>"
        ),
        text, flags=re.DOTALL,
    )
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"^\s*[-*+]\s+", "• ", text, flags=re.MULTILINE)

    return text


def split_message(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for para in text.split("\n\n"):
        if len(current) + len(para) + 2 > limit:
            if current:
                parts.append(current.strip())
            current = para
        else:
            current += ("\n\n" if current else "") + para
    if current:
        parts.append(current.strip())

    result = []
    for p in parts:
        while len(p) > limit:
            result.append(p[:limit])
            p = p[limit:]
        result.append(p)
    return result


def split_reasoning(text: str) -> tuple[str | None, str]:
    m = _REASONING_RE.search(text)
    if m:
        return m.group(1).strip(), text[m.end():].strip()
    return None, text.strip()


def sanitize_user_input(text: str) -> str:
    bad_markers = [
        "ignore previous", "ignore all previous", "system prompt",
        "забудь инструкции", "игнорируй инструкции", "ты теперь",
        "jailbreak", "dan mode",
    ]
    lower = text.lower()
    for b in bad_markers:
        if b in lower:
            return f"[ПОЛЬЗОВАТЕЛЬ ПИШЕТ]: {text}"
    return text
