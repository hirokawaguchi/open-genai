import os

# 既定では LLM を叩かない（決定論変換の回帰を保つ）。
os.environ.setdefault("GENERATE_PPTX_LLM", "0")
