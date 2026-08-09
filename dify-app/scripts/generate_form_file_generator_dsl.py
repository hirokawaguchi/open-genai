#!/usr/bin/env python3
"""Generate FormFileGenerator.yml — form/Excel fields → assemble prompt → file output.

プロンプト組み立ては Dify 側（assemble Code）。源内は開始変数へ値を渡すだけ。
任意の参考資料（ref_files）は document-extractor 経由で LLM に渡す。
様式 Excel のセル注入は dify-app の excel_map（様式と参考資料は別キー）。
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

OUT = Path(__file__).resolve().parents[1] / "dsl" / "FormFileGenerator.yml"

ASSEMBLE_CODE = dedent(
    r'''
    def main(title: str, dept: str, request: str, output_filename: str, output_format: str) -> dict:
        title = (title or "").strip()
        dept = (dept or "").strip()
        request = (request or "").strip()
        fname = (output_filename or "generated").strip() or "generated"
        fmt = (output_format or "markdown").strip().lower() or "markdown"

        prompt = (
            "以下の入力値に基づき、庁内向けの説明資料の本文を作成してください。\n"
            "参考資料がある場合は内容を踏まえ、ない事実は捏造しないこと。\n"
            "前置き・後書きは不要。出力形式のルールに従い本文のみを返すこと。\n\n"
            f"## 事業名\n{title or '(未記入)'}\n\n"
            f"## 担当部署\n{dept or '(未記入)'}\n\n"
            f"## 現状と課題・要望\n{request or '(未記入)'}\n\n"
            "## 作成してほしいもの\n"
            "- 背景と目的\n"
            "- 対応方針（箇条書き）\n"
            "- 今後の進め方\n"
            "- 留意点（不足情報は「要確認」）\n"
        )
        return {
            "prompt": prompt,
            "filename": fname,
            "output_format": fmt,
        }
    '''
).strip("\n")

JOIN_REFS_CODE = dedent(
    r'''
    def main(texts) -> dict:
        if texts is None:
            return {"ref_context": "(参考資料なし)"}
        if isinstance(texts, str):
            body = texts.strip()
            return {"ref_context": body if body else "(参考資料なし)"}
        if isinstance(texts, list):
            parts = []
            for i, t in enumerate(texts, 1):
                chunk = (t or "").strip() if isinstance(t, str) else str(t or "").strip()
                if chunk:
                    parts.append(f"### 参考資料{i}\n\n{chunk}")
            body = "\n\n".join(parts)
            return {"ref_context": body if body else "(参考資料なし)"}
        body = str(texts).strip()
        return {"ref_context": body if body else "(参考資料なし)"}
    '''
).strip("\n")

FINALIZE_CODE = dedent(
    r'''
    def main(text: str, filename: str, output_format: str) -> dict:
        content = (text or "").strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        fmt = (output_format or "markdown").strip().lower() or "markdown"
        ext_map = {
            "markdown": ".md",
            "html": ".html",
            "text": ".txt",
            "json": ".json",
            "docx": ".docx",
            "pptx": ".pptx",
        }
        mime_map = {
            "markdown": "text/markdown",
            "html": "text/html",
            "text": "text/plain",
            "json": "application/json",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        ext = ext_map.get(fmt, ".md")
        mime = mime_map.get(fmt, "text/markdown")

        name = (filename or "generated").strip() or "generated"
        stem = name.rsplit(".", 1)[0] if "." in name else name
        stem = stem or "generated"
        return {
            "content": content,
            "result_text": content,
            "filename": stem + ext,
            "filename_stem": stem,
            "mime_type": mime,
            "output_format": fmt,
        }
    '''
).strip("\n")

PLUGIN_FILE_TOOLS = (
    "kurokobo/file_tools:0.0.2@"
    "8bde7b4d2c30cf22e8f6ce851572af244f7a5776addab94330b820dc2160726c"
)
PLUGIN_MD_EXPORTER = (
    "bowenliang123/md_exporter:3.6.9@"
    "3f027d63e80b44d5d5a9f706871afaef37905b8f8a89a2d152dc530211a8acb1"
)
PLUGIN_AZURE = (
    "langgenius/azure_openai:0.0.28@"
    "9b0339feb86b34393abd921e9cc906192fc46daad3a0f15c1d2a35ba20e8f704"
)

N_START = "1760000000001"
N_ASSEMBLE = "1760000000002"
N_EXTRACT = "1760000000011"
N_JOIN = "1760000000012"
N_LLM = "1760000000003"
N_FINALIZE = "1760000000004"
N_IF = "1760000000005"
N_DOCX = "1760000000006"
N_PPTX = "1760000000007"
N_TEXT = "1760000000008"
N_AGG = "1760000000009"
N_END = "1760000000010"


def _indent_code(code: str, spaces: int = 10) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else pad.rstrip() for line in code.split("\n"))


def _pos(x: int, y: int) -> str:
    return f"""position:
        x: {x}
        y: {y}
      positionAbsolute:
        x: {x}
        y: {y}"""


def build() -> str:
    assemble = _indent_code(ASSEMBLE_CODE)
    join_refs = _indent_code(JOIN_REFS_CODE)
    finalize = _indent_code(FINALIZE_CODE)
    return f"""app:
  description: |
    フォーム（または様式 Excel から注入された開始変数）の値から、Dify 側でプロンプトを組み立て、
    markdown / html / text / json / docx / pptx のファイルを生成するサンプル。
    任意の参考資料（ref_files）を文書抽出して生成に利用できる（様式 Excel とは別キー）。
    源内では Form Spec の desc で入力支援し、キー名を開始変数と一致させる。
    Excel セル注入は dify-app の config.excel_map（opt-in）を使う。
    依存: File Tools, Markdown Exporter, Azure OpenAI。
  icon: 📝
  icon_background: '#E8F3FF'
  icon_type: emoji
  mode: workflow
  name: FormFileGenerator
  use_icon_as_answer_icon: false
dependencies:
- current_identifier: null
  type: marketplace
  value:
    marketplace_plugin_unique_identifier: {PLUGIN_FILE_TOOLS}
- current_identifier: null
  type: marketplace
  value:
    marketplace_plugin_unique_identifier: {PLUGIN_MD_EXPORTER}
- current_identifier: null
  type: marketplace
  value:
    marketplace_plugin_unique_identifier: {PLUGIN_AZURE}
kind: app
version: 0.6.0
workflow:
  conversation_variables: []
  environment_variables: []
  features:
    file_upload:
      enabled: false
      allowed_file_types: []
      allowed_file_extensions: []
      allowed_file_upload_methods: []
      number_limits: 3
    opening_statement: ''
    retriever_resource:
      enabled: false
    sensitive_word_avoidance:
      enabled: false
    speech_to_text:
      enabled: false
    suggested_questions: []
    suggested_questions_after_answer:
      enabled: false
    text_to_speech:
      enabled: false
      language: ''
      voice: ''
  graph:
    edges:
    - data:
        sourceType: start
        targetType: code
      id: edge-start-assemble
      source: '{N_START}'
      sourceHandle: source
      target: '{N_ASSEMBLE}'
      targetHandle: target
      type: custom
    - data:
        sourceType: start
        targetType: document-extractor
      id: edge-start-extract
      source: '{N_START}'
      sourceHandle: source
      target: '{N_EXTRACT}'
      targetHandle: target
      type: custom
    - data:
        sourceType: document-extractor
        targetType: code
      id: edge-extract-join
      source: '{N_EXTRACT}'
      sourceHandle: source
      target: '{N_JOIN}'
      targetHandle: target
      type: custom
    - data:
        sourceType: code
        targetType: llm
      id: edge-assemble-llm
      source: '{N_ASSEMBLE}'
      sourceHandle: source
      target: '{N_LLM}'
      targetHandle: target
      type: custom
    - data:
        sourceType: code
        targetType: llm
      id: edge-join-llm
      source: '{N_JOIN}'
      sourceHandle: source
      target: '{N_LLM}'
      targetHandle: target
      type: custom
    - data:
        sourceType: llm
        targetType: code
      id: edge-llm-finalize
      source: '{N_LLM}'
      sourceHandle: source
      target: '{N_FINALIZE}'
      targetHandle: target
      type: custom
    - data:
        sourceType: code
        targetType: if-else
      id: edge-finalize-if
      source: '{N_FINALIZE}'
      sourceHandle: source
      target: '{N_IF}'
      targetHandle: target
      type: custom
    - data:
        sourceType: if-else
        targetType: tool
      id: edge-if-docx
      source: '{N_IF}'
      sourceHandle: case_docx
      target: '{N_DOCX}'
      targetHandle: target
      type: custom
    - data:
        sourceType: if-else
        targetType: tool
      id: edge-if-pptx
      source: '{N_IF}'
      sourceHandle: case_pptx
      target: '{N_PPTX}'
      targetHandle: target
      type: custom
    - data:
        sourceType: if-else
        targetType: tool
      id: edge-if-text
      source: '{N_IF}'
      sourceHandle: 'false'
      target: '{N_TEXT}'
      targetHandle: target
      type: custom
    - data:
        sourceType: tool
        targetType: variable-aggregator
      id: edge-docx-agg
      source: '{N_DOCX}'
      sourceHandle: source
      target: '{N_AGG}'
      targetHandle: target
      type: custom
    - data:
        sourceType: tool
        targetType: variable-aggregator
      id: edge-pptx-agg
      source: '{N_PPTX}'
      sourceHandle: source
      target: '{N_AGG}'
      targetHandle: target
      type: custom
    - data:
        sourceType: tool
        targetType: variable-aggregator
      id: edge-text-agg
      source: '{N_TEXT}'
      sourceHandle: source
      target: '{N_AGG}'
      targetHandle: target
      type: custom
    - data:
        sourceType: variable-aggregator
        targetType: end
      id: edge-agg-end
      source: '{N_AGG}'
      sourceHandle: source
      target: '{N_END}'
      targetHandle: target
      type: custom
    nodes:
    - data:
        desc: 業務フィールド＋任意の参考資料（様式 Excel は源内 excel_map で別キー）
        selected: false
        title: 開始
        type: start
        variables:
        - label: 事業名
          max_length: 200
          options: []
          required: true
          type: text-input
          variable: title
        - label: 担当部署
          max_length: 200
          options: []
          required: true
          type: text-input
          variable: dept
        - label: 現状と課題・要望
          max_length: 8000
          options: []
          required: true
          type: paragraph
          variable: request
        - allowed_file_extensions: []
          allowed_file_types:
          - document
          allowed_file_upload_methods:
          - local_file
          - remote_url
          label: 参考資料（任意・複数可）
          max_length: 10
          number_limits: 10
          options: []
          required: false
          type: file-list
          variable: ref_files
        - default: generated
          label: 出力ファイル名（拡張子なし可）
          max_length: 200
          options: []
          required: false
          type: text-input
          variable: output_filename
        - default: markdown
          label: 出力形式
          options:
          - markdown
          - html
          - text
          - json
          - docx
          - pptx
          required: false
          type: select
          variable: output_format
      height: 280
      id: '{N_START}'
      {_pos(0, 280)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{assemble}
        code_language: python3
        desc: 開始変数からプロンプトを組み立てる（正本はここ）
        outputs:
          prompt:
            children: null
            type: string
          filename:
            children: null
            type: string
          output_format:
            children: null
            type: string
        selected: false
        title: プロンプト組み立て
        type: code
        variables:
        - value_selector: ['{N_START}', title]
          variable: title
        - value_selector: ['{N_START}', dept]
          variable: dept
        - value_selector: ['{N_START}', request]
          variable: request
        - value_selector: ['{N_START}', output_filename]
          variable: output_filename
        - value_selector: ['{N_START}', output_format]
          variable: output_format
      height: 54
      id: '{N_ASSEMBLE}'
      {_pos(280, 200)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: 参考資料からテキストを抽出（未アップロード時は空）
        is_array_file: true
        selected: false
        title: 参考資料の抽出
        type: document-extractor
        variable_selector:
        - '{N_START}'
        - ref_files
      height: 90
      id: '{N_EXTRACT}'
      {_pos(280, 420)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{join_refs}
        code_language: python3
        desc: 抽出テキストを LLM 用コンテキストに整形
        outputs:
          ref_context:
            children: null
            type: string
        selected: false
        title: 参考資料の整形
        type: code
        variables:
        - value_selector: ['{N_EXTRACT}', text]
          variable: texts
      height: 54
      id: '{N_JOIN}'
      {_pos(560, 420)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        context:
          enabled: false
          variable_selector: []
        desc: 組み立て済みプロンプトと参考資料から本文を生成
        model:
          completion_params:
            temperature: 0.3
          mode: chat
          name: gpt-4.1
          provider: langgenius/azure_openai/azure_openai
        prompt_template:
        - id: ffg-sys
          role: system
          text: |
            あなたは庁内文書の起草アシスタントです。
            - 前置き・後書き・説明文は書かない（本文のみ）
            - 入力や参考資料にない事実を捏造しない。不足は「要確認」と明記
            - コードフェンスで全体を囲まない
            - markdown / docx: 見出し・箇条書きの Markdown
            - text: プレーンテキスト
            - json: 有効な JSON のみ
            - pptx: Pandoc スライド形式。各スライドを --- で区切る
            - html: 単一の自己完結 HTML のみ（外部リソース・script 禁止）
        - id: ffg-user
          role: user
          text: |
            ## 出力形式

            {{{{#{N_ASSEMBLE}.output_format#}}}}

            ## 指示

            {{{{#{N_ASSEMBLE}.prompt#}}}}

            ## 参考資料

            {{{{#{N_JOIN}.ref_context#}}}}
        selected: false
        title: ファイル生成 LLM
        type: llm
        variables: []
        vision:
          enabled: false
      height: 90
      id: '{N_LLM}'
      {_pos(840, 300)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{finalize}
        code_language: python3
        desc: 本文整形とファイル名・形式の確定
        outputs:
          content:
            children: null
            type: string
          result_text:
            children: null
            type: string
          filename:
            children: null
            type: string
          filename_stem:
            children: null
            type: string
          mime_type:
            children: null
            type: string
          output_format:
            children: null
            type: string
        selected: false
        title: 出力整形
        type: code
        variables:
        - value_selector: ['{N_LLM}', text]
          variable: text
        - value_selector: ['{N_ASSEMBLE}', filename]
          variable: filename
        - value_selector: ['{N_ASSEMBLE}', output_format]
          variable: output_format
      height: 54
      id: '{N_FINALIZE}'
      {_pos(1120, 300)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        cases:
        - case_id: case_docx
          conditions:
          - comparison_operator: is
            id: cond-docx
            value: docx
            varType: string
            variable_selector: ['{N_FINALIZE}', output_format]
          id: case_docx
          logical_operator: and
        - case_id: case_pptx
          conditions:
          - comparison_operator: is
            id: cond-pptx
            value: pptx
            varType: string
            variable_selector: ['{N_FINALIZE}', output_format]
          id: case_pptx
          logical_operator: and
        desc: 出力形式に応じて変換ツールを分岐
        selected: false
        title: 出力形式分岐
        type: if-else
      height: 180
      id: '{N_IF}'
      {_pos(1400, 260)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: Markdown を DOCX に変換
        is_team_authorization: true
        paramSchemas: []
        params:
          md_text: ''
          output_filename: ''
        plugin_id: bowenliang123/md_exporter
        plugin_unique_identifier: {PLUGIN_MD_EXPORTER}
        provider_icon: ''
        provider_id: bowenliang123/md_exporter/md_exporter
        provider_name: bowenliang123/md_exporter/md_exporter
        provider_type: builtin
        selected: false
        title: DOCX 変換
        tool_configurations:
          enable_toc:
            type: constant
            value: 'false'
        tool_description: Markdown を DOCX に変換する
        tool_label: Markdown ⮕ DOCX
        tool_name: md_to_docx
        tool_node_version: '2'
        tool_parameters:
          md_text:
            type: mixed
            value: '{{{{#{N_FINALIZE}.content#}}}}'
          output_filename:
            type: mixed
            value: '{{{{#{N_FINALIZE}.filename_stem#}}}}'
        type: tool
      height: 120
      id: '{N_DOCX}'
      {_pos(1680, 80)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: Markdown を PPTX に変換
        is_team_authorization: true
        paramSchemas: []
        params:
          md_text: ''
          output_filename: ''
        plugin_id: bowenliang123/md_exporter
        plugin_unique_identifier: {PLUGIN_MD_EXPORTER}
        provider_icon: ''
        provider_id: bowenliang123/md_exporter/md_exporter
        provider_name: bowenliang123/md_exporter/md_exporter
        provider_type: builtin
        selected: false
        title: PPTX 変換
        tool_configurations: {{}}
        tool_description: Markdown を PPTX に変換する
        tool_label: Markdown ⮕ PPTX
        tool_name: md_to_pptx
        tool_node_version: '2'
        tool_parameters:
          md_text:
            type: mixed
            value: '{{{{#{N_FINALIZE}.content#}}}}'
          output_filename:
            type: mixed
            value: '{{{{#{N_FINALIZE}.filename_stem#}}}}'
        type: tool
      height: 120
      id: '{N_PPTX}'
      {_pos(1680, 280)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: markdown / html / text / json をファイル保存
        is_team_authorization: true
        paramSchemas: []
        params:
          content: ''
          encoding: ''
          filename: ''
          format: ''
          mime_type: ''
        plugin_id: kurokobo/file_tools
        plugin_unique_identifier: {PLUGIN_FILE_TOOLS}
        provider_icon: ''
        provider_id: kurokobo/file_tools/file_tools
        provider_name: kurokobo/file_tools/file_tools
        provider_type: builtin
        selected: false
        title: テキストファイル保存
        tool_configurations:
          format:
            type: constant
            value: text
        tool_description: テキストをファイルとして保存
        tool_label: ファイルとして保存
        tool_name: save_as_file
        tool_node_version: '2'
        tool_parameters:
          content:
            type: mixed
            value: '{{{{#{N_FINALIZE}.content#}}}}'
          encoding:
            type: mixed
            value: utf-8
          filename:
            type: mixed
            value: '{{{{#{N_FINALIZE}.filename#}}}}'
          mime_type:
            type: mixed
            value: '{{{{#{N_FINALIZE}.mime_type#}}}}'
        type: tool
      height: 120
      id: '{N_TEXT}'
      {_pos(1680, 480)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        advanced_settings: null
        desc: 形式別の成果物ファイルを集約
        output_type: array[file]
        selected: false
        title: 成果物集約
        type: variable-aggregator
        variables:
        - ['{N_DOCX}', files]
        - ['{N_PPTX}', files]
        - ['{N_TEXT}', files]
      height: 110
      id: '{N_AGG}'
      {_pos(1960, 300)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: 生成本文と成果物ファイルを返す
        outputs:
        - value_selector: ['{N_FINALIZE}', result_text]
          value_type: string
          variable: result
        - value_selector: ['{N_AGG}', output]
          value_type: array[file]
          variable: generated_file
        - value_selector: ['{N_FINALIZE}', filename]
          value_type: string
          variable: filename
        selected: false
        title: 終了
        type: end
      height: 140
      id: '{N_END}'
      {_pos(2240, 280)}
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    viewport:
      x: 0
      y: 0
      zoom: 0.7
  rag_pipeline_variables: []
"""


def main() -> None:
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
