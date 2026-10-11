"""チャット回答の補足画像。

リンクを押したときにだけ、画像生成が使えるモデルで1枚作る。
絵にならない回答は画像なしにする。
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any

from . import image_gen, llm

FILES_DIR = os.environ.get("FILES_DIR", "/data/files")
MAX_ANSWER_CHARS = 4000

_NONE_RE = re.compile(r"NONE[.。]?", re.IGNORECASE)

_SYSTEM = """あなたは説明画像の編集者です。渡された回答を見て、1枚の絵にすると理解しやすくなるときだけ、英語の画像プロンプトを1行で返します。

絵にするのは、物の様子、場所、手順の場面、全体の姿が回答にあるときです。
絵にしないのは、定義、短い事実、数値、制度の説明、文章の推敲です。そのときは NONE とだけ返してください。

プロンプトは回答に書いてあるものだけを描きます。実在の人物、ロゴ、作品名、画面内の文字は入れません。
説明文は付けず、NONE か英語の1行だけを返してください。
"""


def parse_image_prompt(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text or _NONE_RE.fullmatch(text):
        return {"status": "none"}
    line = ""
    for part in text.splitlines():
        part = part.strip().strip("`")
        if not part or part.lower() == "mermaid":
            continue
        line = part
        break
    if not line or _NONE_RE.fullmatch(line):
        return {"status": "none"}
    return {"status": "ready", "prompt": line[:500]}


def remove_stored_images(keys: list[str]) -> None:
    root = os.path.abspath(FILES_DIR)
    for key in keys:
        full = os.path.normpath(os.path.join(root, key))
        if not full.startswith(root + os.sep):
            continue
        try:
            os.remove(full)
        except OSError:
            pass


def _write_png(chat_id: str, message_id: str, image_b64: str) -> str:
    raw = base64.b64decode(image_b64)
    key = f"image-supplement/{chat_id}/{message_id}.png"
    full = os.path.normpath(os.path.join(os.path.abspath(FILES_DIR), key))
    root = os.path.abspath(FILES_DIR)
    if not full.startswith(root + os.sep):
        raise ValueError("画像の保存先が不正です")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(raw)
    return key


def read_image_data_url(file_key: str) -> str | None:
    full = os.path.normpath(os.path.join(os.path.abspath(FILES_DIR), file_key))
    root = os.path.abspath(FILES_DIR)
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return None
    with open(full, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


async def resolve_image_model() -> dict[str, str] | None:
    """使える画像生成へ向ける。ローカル SD を優先し、無ければ登録済みモデル。"""
    if await image_gen.is_sd_up():
        return {"modelId": image_gen.LOCAL_SD_MODEL_ID}
    providers = image_gen.load_image_providers()
    if not providers:
        return None
    return {"modelId": next(iter(providers))}


def _user_prompt(answer: str, question: str) -> str:
    body = (answer or "").strip()
    if len(body) > MAX_ANSWER_CHARS:
        body = body[:MAX_ANSWER_CHARS]
    question = (question or "").strip()
    if len(question) > 1000:
        question = question[:1000]
    parts = ["次の回答を1枚の絵にできるなら英語のプロンプトを、できなければ NONE を返してください。"]
    if question:
        parts.append(f"\n質問:\n{question}")
    parts.append(f"\n回答:\n{body}")
    return "\n".join(parts)


async def build_image(
    answer: str,
    question: str,
    chat_id: str,
    message_id: str,
    text_model: dict[str, Any] | None,
) -> dict[str, str]:
    image_model = await resolve_image_model()
    if image_model is None:
        raise image_gen.ImageGenError(
            "画像生成のモデルが利用できません。",
            status=503,
            code="image_unavailable",
        )
    raw = await llm.chat_once(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_prompt(answer, question)},
        ],
        text_model,
    )
    parsed = parse_image_prompt(raw)
    if parsed["status"] != "ready":
        return {"status": "none"}
    params = {
        "textPrompt": [
            {"text": parsed["prompt"], "weight": 1},
            {"text": "text, watermark, logo, low quality", "weight": -1},
        ],
        "width": 1024,
        "height": 1024,
        "step": 20,
        "cfgScale": 7,
    }
    image_b64 = await image_gen.generate_image_base64(params, image_model)
    file_key = _write_png(chat_id, message_id, image_b64)
    return {"status": "ready", "prompt": parsed["prompt"], "fileKey": file_key}
