"""紙面の文字書き換え。LLM の前後の整形だけを持つ。"""


def clean_rewrite(raw: str) -> str:
    """モデルが付けがちな引用符を外し、本文だけを残す。"""
    text = (raw or "").strip()
    fences = (("「", "」"), ('"', '"'), ("'", "'"))
    for start, end in fences:
        if text.startswith(start) and text.endswith(end) and len(text) > len(start) + len(end):
            return text[len(start) : -len(end)].strip()
    return text
