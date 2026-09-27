"""共有ナレッジの管理判定。rag-app 全体は起動せず、判定関数だけを読む。"""

from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _rag_auth():
    src = (ROOT / "rag-app/app/main.py").read_text()
    tree = ast.parse(src)
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & {"TENANT_SCOPE_ADMIN_GROUP", "DEFAULT_SCOPE"}:
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "_user_groups",
            "_is_admin",
            "_can_manage",
        }:
            keep.append(node)
    mod = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: dict = {"os": os}
    exec(compile(mod, "rag-auth", "exec"), ns)
    return ns


def test_common_knowledge_manage_allows_signed_tenant_admin() -> None:
    rag = _rag_auth()
    common = rag["DEFAULT_SCOPE"]
    assert rag["TENANT_SCOPE_ADMIN_GROUP"] == "TenantScopeAdmin"
    assert rag["_can_manage"](common, rag["_is_admin"]("UserGroup,TenantScopeAdmin"))
    assert rag["_can_manage"](common, rag["_is_admin"]("SystemAdminGroup"))
    assert not rag["_can_manage"](common, rag["_is_admin"]("UserGroup"))
    assert not rag["_can_manage"](common, rag["_is_admin"]("UserGroup,TenantScopeAdminX"))
    assert rag["_can_manage"]("team-1", rag["_is_admin"]("UserGroup"))
