"""領域クロップと OCR（プラガブル）。

DOCCHECK_OCR_ENGINE:
  - hybrid（既定）: PP-OCR（本家→RapidOCR）→ 低信頼/空なら Vision LLM
  - paddleocr: 本家 PaddleOCR を優先。未導入・arm64 は RapidOCR へフォールバック
  - paddle / rapidocr: RapidOCR（ONNX）のみ
  - vision: ローカル Vision LLM
  - auto: hybrid と同義
  - tesseract / none

本家パッケージは任意（requirements-paddleocr.txt）。既定イメージは RapidOCR 同梱。
"""

from __future__ import annotations

import base64
import io
import os
import platform
import re
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageOps

ENGINE = (os.environ.get("DOCCHECK_OCR_ENGINE") or "hybrid").strip().lower()
OVERLAP_RATIO = float(os.environ.get("DOCCHECK_OVERLAP_RATIO", "0.08"))
DATA_DIR = Path(os.environ.get("DOCCHECK_DATA_DIR", "/data"))
IMAGES_DIR = DATA_DIR / "images"
# A4 長辺 @300dpi 相当。投入画像をこの長辺に正規化して OCR しやすくする
OCR_TARGET_DPI = int(os.environ.get("DOCCHECK_OCR_TARGET_DPI", "300"))
OCR_LONG_EDGE = int(os.environ.get("DOCCHECK_OCR_LONG_EDGE", "3508"))
OCR_NORMALIZE = os.environ.get("DOCCHECK_OCR_NORMALIZE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
VISION_MODEL = (
    os.environ.get("DOCCHECK_VISION_MODEL")
    or os.environ.get("DOCCHECK_DEFAULT_VISION_MODEL")
    or "gemma3:27b"
)
VISION_CONFIDENCE = float(os.environ.get("DOCCHECK_VISION_CONFIDENCE", "0.55"))
PADDLE_MIN_CONF = float(os.environ.get("DOCCHECK_PADDLE_MIN_CONF", "0.50"))
# arm64 でも本家を試す（通常は非推奨）
FORCE_OFFICIAL = os.environ.get("DOCCHECK_PADDLEOCR_FORCE", "").strip() in (
    "1",
    "true",
    "yes",
)
PADDLEOCR_LANG = os.environ.get("DOCCHECK_PADDLEOCR_LANG", "japan")

_rapid_ocr: Any | None = None
_rapid_ocr_failed = False
_official_ocr: Any | None = None
_official_ocr_failed = False
_official_ocr_mode: str | None = None  # "v2" | "v3"
_last_ppocr_backend: Literal["paddleocr", "rapidocr", "none"] = "none"


def ensure_dirs() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def is_arm64() -> bool:
    machine = platform.machine().lower()
    return machine in ("aarch64", "arm64")


def official_paddleocr_available() -> bool:
    """本家を使う条件: パッケージ導入済み、かつ（amd64 または FORCE）。"""
    if is_arm64() and not FORCE_OFFICIAL:
        return False
    try:
        import paddleocr  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def resolve_ppocr_backend() -> str:
    """設定上、PP-OCR 系で優先される実装名。"""
    if ENGINE in ("paddle", "rapidocr"):
        return "rapidocr"
    if ENGINE in ("paddleocr", "hybrid", "auto"):
        if official_paddleocr_available():
            return "paddleocr"
        return "rapidocr"
    return "none"


def ocr_status() -> dict[str, Any]:
    return {
        "ocr_engine": ENGINE,
        "ppocr_backend": resolve_ppocr_backend(),
        "ppocr_last_backend": _last_ppocr_backend,
        "official_paddleocr_available": official_paddleocr_available(),
        "is_arm64": is_arm64(),
        "paddleocr_force": FORCE_OFFICIAL,
        "vision_model": VISION_MODEL,
        "paddle_min_conf": PADDLE_MIN_CONF,
    }


def decode_image_bytes(data_b64: str) -> bytes:
    raw = data_b64.strip()
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def normalize_for_ocr(image_bytes: bytes) -> tuple[bytes, int]:
    """スキャン画像を OCR 向けに正規化する。

    - グレースケール化
    - 軽いコントラスト補正
    - 長辺を OCR_LONG_EDGE（既定: A4@300dpi 相当）にリサイズ
    戻り値: (png_bytes, 記録用 dpi)
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("L", "RGB", "RGBA"):
        img = img.convert("RGB")
    if not OCR_NORMALIZE:
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), OCR_TARGET_DPI

    gray = img.convert("L")
    try:
        gray = ImageOps.autocontrast(gray, cutoff=0.5)
    except Exception:  # noqa: BLE001
        pass
    w, h = gray.size
    long_edge = max(w, h)
    target = max(640, OCR_LONG_EDGE)
    if long_edge > 0 and abs(long_edge - target) / long_edge > 0.02:
        scale = target / long_edge
        gray = gray.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    buf = io.BytesIO()
    # 下流クロップ／表示のため RGB PNG で保存（中身はグレー）
    gray.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), OCR_TARGET_DPI


def save_page_image(doc_id: str, page_index: int, image_bytes: bytes) -> tuple[Path, int]:
    ensure_dirs()
    normalized, dpi = normalize_for_ocr(image_bytes)
    path = IMAGES_DIR / f"{doc_id}_p{page_index}.png"
    path.write_bytes(normalized)
    return path, dpi


def crop_region(
    page_path: Path,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    out_path: Path,
    overlap_ratio: float = OVERLAP_RATIO,
) -> Path:
    """正規化座標 (0-1) でクロップ。周囲に overlap を付与。"""
    img = Image.open(page_path).convert("RGB")
    iw, ih = img.size
    ox = w * overlap_ratio
    oy = h * overlap_ratio
    left = max(0, int((x - ox) * iw))
    top = max(0, int((y - oy) * ih))
    right = min(iw, int((x + w + ox) * iw))
    bottom = min(ih, int((y + h + oy) * ih))
    if right <= left or bottom <= top:
        raise ValueError("invalid region bounds")
    cropped = img.crop((left, top, right, bottom))
    cw, ch = cropped.size
    if cw < 80 or ch < 40:
        scale = max(80 / max(cw, 1), 40 / max(ch, 1), 2.0)
        cropped = cropped.resize(
            (max(1, int(cw * scale)), max(1, int(ch * scale))),
            Image.Resampling.LANCZOS,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(out_path, format="PNG")
    return out_path


def run_ocr(
    image_path: Path,
    *,
    field_type: str = "text",
    is_handwriting: bool = True,
) -> tuple[str, float]:
    """(text, confidence 0-1) を返す（従来互換。fallback 相当）。"""
    res = run_ocr_ex(
        image_path,
        field_type=field_type,
        is_handwriting=is_handwriting,
        ocr_mode="fallback",
    )
    return res["text"], res["confidence"]


def _run_ppocr_by_engine(image_path: Path) -> tuple[str, float, str | None]:
    """設定エンジンに応じて PP-OCR 系（または tesseract）を1回実行する。

    戻り値: (text, confidence, source)。Vision 専用/none のときは source=None。
    """
    engine = ENGINE
    if engine in ("hybrid", "auto", "paddleocr"):
        text, conf = _ocr_ppocr(image_path, prefer_official=True)
        return text, conf, "ppocr"
    if engine in ("paddle", "rapidocr"):
        text, conf = _ocr_ppocr(image_path, prefer_official=False)
        return text, conf, "ppocr"
    if engine == "tesseract":
        text, conf = _ocr_tesseract(image_path)
        return text, conf, "tesseract"
    return "", 0.0, None


def run_ocr_ex(
    image_path: Path,
    *,
    field_type: str = "text",
    is_handwriting: bool = True,
    ocr_mode: str = "fallback",
    skip_vision: bool = False,
) -> dict[str, Any]:
    """テンプレの OCR モードに応じて PP-OCR / Vision を実行する。

    戻り値 dict:
      - text / confidence: 主候補（PP-OCR。空/低信頼で Vision 補完時は Vision）
      - vision_text / vision_confidence: 両方実行（always・vision エンジン）時のみ
      - sources: 実行したエンジン名の一覧
    """
    mode = ocr_mode if ocr_mode in ("ppocr", "fallback", "always") else "fallback"
    engine = ENGINE
    sources: list[str] = []

    if engine == "none":
        return {
            "text": "",
            "confidence": 0.0,
            "vision_text": "",
            "vision_confidence": 0.0,
            "sources": sources,
        }

    vision_only = engine in ("vision", "vlm")

    pp_text, pp_conf = "", 0.0
    if not vision_only:
        pp_text, pp_conf, pp_src = _run_ppocr_by_engine(image_path)
        if pp_src:
            sources.append(pp_src)

    text, conf = pp_text, pp_conf
    vision_text, vision_conf = "", 0.0

    def _run_vision() -> tuple[str, float]:
        return _ocr_vision(
            image_path, field_type=field_type, is_handwriting=is_handwriting
        )

    if vision_only:
        # PP-OCR が使えない構成。Vision を主候補にする（skip_vision でも読取手段が無い）
        vtext, vconf = _run_vision()
        sources.append("vision")
        return {
            "text": vtext,
            "confidence": vconf,
            "vision_text": "",
            "vision_confidence": 0.0,
            "sources": sources,
        }

    want_vision = not skip_vision and mode != "ppocr"
    if want_vision:
        if mode == "always":
            vtext, vconf = _run_vision()
            sources.append("vision")
            vision_text, vision_conf = vtext, vconf
            # 主候補が空/低信頼なら Vision を主に昇格
            if vtext and ((not pp_text) or pp_conf < PADDLE_MIN_CONF):
                text, conf = vtext, vconf
        else:  # fallback: 低信頼/空のときだけ補完し、主候補に畳み込む
            if (not pp_text) or pp_conf < PADDLE_MIN_CONF:
                vtext, vconf = _run_vision()
                sources.append("vision")
                if vtext:
                    text, conf = vtext, vconf

    return {
        "text": text,
        "confidence": conf,
        "vision_text": vision_text,
        "vision_confidence": vision_conf,
        "sources": sources,
    }


def _ocr_ppocr(image_path: Path, *, prefer_official: bool) -> tuple[str, float]:
    """本家 PaddleOCR → RapidOCR の二段構え。"""
    global _last_ppocr_backend
    if prefer_official and official_paddleocr_available():
        text, conf = _ocr_paddleocr_official(image_path)
        if text:
            _last_ppocr_backend = "paddleocr"
            return text, conf
        # 本家が空/失敗なら RapidOCR へ
        print("[doccheck-ocr] official PaddleOCR empty/failed → RapidOCR fallback")
    text, conf = _ocr_rapidocr(image_path)
    _last_ppocr_backend = "rapidocr" if text or conf else "none"
    return text, conf


def _get_official_ocr() -> Any | None:
    global _official_ocr, _official_ocr_failed, _official_ocr_mode
    if _official_ocr is not None:
        return _official_ocr
    if _official_ocr_failed:
        return None
    try:
        from paddleocr import PaddleOCR

        # PaddleOCR 2.x
        try:
            _official_ocr = PaddleOCR(
                use_angle_cls=True,
                lang=PADDLEOCR_LANG,
                show_log=False,
            )
            _official_ocr_mode = "v2"
            print(
                f"[doccheck-ocr] official PaddleOCR ready (v2 API, lang={PADDLEOCR_LANG})"
            )
            return _official_ocr
        except TypeError:
            # PaddleOCR 3.x など引数差異
            _official_ocr = PaddleOCR(lang=PADDLEOCR_LANG)
            _official_ocr_mode = "v3"
            print(
                f"[doccheck-ocr] official PaddleOCR ready (v3 API, lang={PADDLEOCR_LANG})"
            )
            return _official_ocr
    except Exception as e:  # noqa: BLE001
        _official_ocr_failed = True
        print(f"[doccheck-ocr] official PaddleOCR init failed: {e}")
        return None


def _ocr_paddleocr_official(image_path: Path) -> tuple[str, float]:
    import numpy as np

    engine = _get_official_ocr()
    if engine is None:
        return "", 0.0
    try:
        arr = np.array(Image.open(image_path).convert("RGB"))
        parts: list[str] = []
        scores: list[float] = []

        if _official_ocr_mode == "v3" and hasattr(engine, "predict"):
            # PaddleOCR 3.x predict API（戻り値は実装差があるため寛容にパース）
            preds = engine.predict(arr)
            _collect_from_paddle_predict(preds, parts, scores)
        else:
            result = engine.ocr(arr, cls=True)
            _collect_from_paddle_v2(result, parts, scores)

        return _join_ocr_parts(parts, scores)
    except Exception as e:  # noqa: BLE001
        print(f"[doccheck-ocr] official PaddleOCR failed: {e}")
        return "", 0.0


def _collect_from_paddle_v2(
    result: Any, parts: list[str], scores: list[float]
) -> None:
    if not result:
        return
    # 典型: [ [ [box, (text, conf)], ... ] ] またはページなしの list
    pages = result if isinstance(result, list) else [result]
    for page in pages:
        if not page:
            continue
        for line in page:
            if not line or len(line) < 2:
                continue
            rec = line[1]
            if isinstance(rec, (list, tuple)) and len(rec) >= 2:
                t = _clean_ocr_text(str(rec[0] or ""))
                if not t:
                    continue
                parts.append(t)
                try:
                    scores.append(float(rec[1]))
                except (TypeError, ValueError):
                    scores.append(0.5)
            elif isinstance(rec, str):
                t = _clean_ocr_text(rec)
                if t:
                    parts.append(t)
                    scores.append(0.5)


def _collect_from_paddle_predict(
    preds: Any, parts: list[str], scores: list[float]
) -> None:
    if preds is None:
        return
    items = preds if isinstance(preds, list) else [preds]
    for item in items:
        if item is None:
            continue
        # dict-like
        if isinstance(item, dict):
            texts = item.get("rec_texts") or item.get("texts") or []
            confs = item.get("rec_scores") or item.get("scores") or []
            for i, t0 in enumerate(texts):
                t = _clean_ocr_text(str(t0 or ""))
                if not t:
                    continue
                parts.append(t)
                try:
                    scores.append(float(confs[i]))
                except Exception:  # noqa: BLE001
                    scores.append(0.5)
            continue
        # object with attributes
        texts = getattr(item, "rec_texts", None) or getattr(item, "texts", None)
        confs = getattr(item, "rec_scores", None) or getattr(item, "scores", None)
        if texts:
            for i, t0 in enumerate(texts):
                t = _clean_ocr_text(str(t0 or ""))
                if not t:
                    continue
                parts.append(t)
                try:
                    scores.append(float(confs[i]))  # type: ignore[index]
                except Exception:  # noqa: BLE001
                    scores.append(0.5)


def _get_rapid_ocr() -> Any | None:
    global _rapid_ocr, _rapid_ocr_failed
    if _rapid_ocr is not None:
        return _rapid_ocr
    if _rapid_ocr_failed:
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR

        _rapid_ocr = RapidOCR()
        return _rapid_ocr
    except Exception as e:  # noqa: BLE001
        _rapid_ocr_failed = True
        print(f"[doccheck-ocr] RapidOCR init failed: {e}")
        return None


def _ocr_rapidocr(image_path: Path) -> tuple[str, float]:
    """PP-OCR（RapidOCR / ONNX）。本家未導入・arm64 向け。"""
    import numpy as np

    engine = _get_rapid_ocr()
    if engine is None:
        return "", 0.0
    try:
        arr = np.array(Image.open(image_path).convert("RGB"))
        result, _elapse = engine(arr)
        if not result:
            return "", 0.0
        parts: list[str] = []
        scores: list[float] = []
        for item in result:
            if not item or len(item) < 3:
                continue
            t = _clean_ocr_text(str(item[1] or ""))
            if not t:
                continue
            parts.append(t)
            try:
                scores.append(float(item[2]))
            except (TypeError, ValueError):
                scores.append(0.5)
        return _join_ocr_parts(parts, scores)
    except Exception as e:  # noqa: BLE001
        print(f"[doccheck-ocr] rapidocr failed: {e}")
        return "", 0.0


# 後方互換エイリアス
def _ocr_paddle(image_path: Path) -> tuple[str, float]:
    return _ocr_ppocr(image_path, prefer_official=True)


def _join_ocr_parts(parts: list[str], scores: list[float]) -> tuple[str, float]:
    if not parts:
        return "", 0.0
    text = " ".join(parts)
    if len(parts) > 1:
        joined = "".join(parts)
        if re.fullmatch(r"[\w\u3040-\u30ff\u3400-\u9fff\-年月日/.]+", joined):
            text = joined
    conf = sum(scores) / len(scores) if scores else 0.5
    return text, conf


def _ocr_tesseract(image_path: Path) -> tuple[str, float]:
    try:
        import pytesseract  # type: ignore
    except ImportError:
        return "", 0.0
    try:
        text = pytesseract.image_to_string(Image.open(image_path), lang="jpn+eng")
        text = _clean_ocr_text(text or "")
        conf = 0.55 if text else 0.0
        return text, conf
    except Exception as e:  # noqa: BLE001
        print(f"[doccheck-ocr] tesseract failed: {e}")
        return "", 0.0


def _ocr_vision(
    image_path: Path,
    *,
    field_type: str = "text",
    is_handwriting: bool = True,
) -> tuple[str, float]:
    """OpenAI 互換の vision モデルで読取（失敗時は空）。"""
    import httpx

    base = (
        os.environ.get("OPENAI_BASE_URL")
        or (
            os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
            + "/v1"
        )
    ).rstrip("/")
    api_key = os.environ.get("OPENAI_API_KEY", "ollama")
    model = VISION_MODEL
    raw = image_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    style = "手書きまたは印刷の" if is_handwriting else "印刷された"
    hint = {
        "date": "日付として読み取り、可能なら元の表記のまま返してください。",
        "number": "数字・記号を優先して読み取ってください。",
        "kana": "かな文字を優先して読み取ってください。",
        "text_multi": "複数行ある場合は改行を保持してそのまま読み取ってください。",
    }.get(field_type, "文字をそのまま読み取ってください。")
    prompt = (
        f"これは申請書類の一部分の画像です。{style}文字だけを読み取ってください。\n"
        f"{hint}\n"
        "ルール:\n"
        "- 読み取った文字列のみを返す（説明・引用符・Markdown 禁止）\n"
        "- 枠線・ラベル・ノイズは無視する\n"
        "- 読めない場合は空文字のみ返す"
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 256,
        "temperature": 0,
    }
    try:
        with httpx.Client(timeout=180.0) as client:
            res = client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if res.status_code >= 400:
                print(
                    f"[doccheck-ocr] vision HTTP {res.status_code}: "
                    f"{res.text[:300]} (model={model})"
                )
                return "", 0.0
            data = res.json()
        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if field_type == "text_multi":
            text = _clean_ocr_text_multiline(text or "")
        else:
            text = _clean_ocr_text(text or "")
        if not text:
            return "", 0.0
        return text, VISION_CONFIDENCE
    except Exception as e:  # noqa: BLE001
        print(f"[doccheck-ocr] vision failed (model={model}): {e}")
        return "", 0.0


def _clean_ocr_text_multiline(text: str) -> str:
    """複数行テキスト用：各行を整えつつ改行を保持する。"""
    s = (text or "").strip().strip("`")
    lines = [ln.rstrip() for ln in s.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _clean_ocr_text(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(
        r"^(読み取った文字[:：]|結果[:：]|OCR[:：]|Answer[:：])\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = s.strip().strip("`\"'「」『』")
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return ""
    if len(lines) > 1 and any(
        x in lines[0] for x in ("です", "ます", "画像", "読め")
    ):
        lines = lines[1:] or lines
    return lines[0]


def pdf_to_page_pngs(pdf_bytes: bytes, *, max_pages: int = 20) -> list[bytes]:
    """PDF を各ページ PNG バイト列へ（埋め込み画像の抽出）。"""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    out: list[bytes] = []
    for i, page in enumerate(reader.pages[:max_pages]):
        try:
            resources = page.get("/Resources") or {}
            xobject = resources.get("/XObject")
            if xobject is None:
                continue
            xobject = xobject.get_object()
            for _name, obj in xobject.items():
                obj = obj.get_object()
                if obj.get("/Subtype") == "/Image":
                    data = obj.get_data()
                    try:
                        img = Image.open(io.BytesIO(data)).convert("RGB")
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        out.append(buf.getvalue())
                        break
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            continue
    return out
