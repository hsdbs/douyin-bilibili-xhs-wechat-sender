# -*- coding: utf-8 -*-
"""
wxid ↔ 显示名 映射模块

背景：检测层用 WeFlow（返回 wxid），发送层用 wxauto4（只能用"显示名"定位会话）。
本模块从 WeFlow 拉取会话/联系人，建立 wxid -> displayName 的映射，供发送时反查。

依赖：urllib（标准库），无需额外安装。
WeFlow 地址 / Token 由 config/config.json 统一管理（可在 Web 面板配置）。
"""
import json
import os
import urllib.request
import urllib.parse

from core.config import DATA_DIR, get_config

# 默认值（config 缺失时兜底）
DEFAULT_BASE_URL = "http://127.0.0.1:5031"
DEFAULT_TOKEN = "wf_douyin_flow_2026"

MAPPING_FILE = os.path.join(DATA_DIR, "wxid_displayname_mapping.json")


def _base_url():
    try:
        return get_config().get("weflow", {}).get("base_url") or DEFAULT_BASE_URL
    except Exception:
        return DEFAULT_BASE_URL


def _token():
    try:
        return get_config().get("weflow", {}).get("token") or DEFAULT_TOKEN
    except Exception:
        return DEFAULT_TOKEN


def _get(path, params=None):
    """GET WeFlow API，返回解析后的 JSON dict（失败时返回 {'error': ...}）。"""
    url = _base_url() + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def test_connection():
    """测试 WeFlow 连通性，返回 (ok, detail)。"""
    r = _get("/api/v1/sessions", {"limit": 1})
    if "error" in r:
        return False, r["error"]
    return True, "WeFlow 连接成功"


def fetch_mapping():
    """从 WeFlow 拉取 sessions + contacts，合并建立 wxid -> displayName 映射。

    返回 dict：{ 'filehelper': '文件传输助手', 'wxid_xxx': '张三', 'xxx@chatroom': '项目群', ... }
    """
    mapping = {}

    # 1) 会话列表（含私聊 wxid、群 @chatroom、filehelper、@openim）
    s = _get("/api/v1/sessions", {"limit": 10000})
    if "error" not in s:
        for item in s.get("sessions", []):
            u = item.get("username")
            d = item.get("displayName")
            if u and d:
                mapping[u] = d

    # 2) 联系人列表（补充 nickname/remark 更精确的显示名，私聊专用）
    c = _get("/api/v1/contacts", {"limit": 10000})
    if "error" not in c:
        for item in c.get("contacts", []):
            u = item.get("username")
            # 优先级：remark(备注) > displayName > nickname
            d = item.get("remark") or item.get("displayName") or item.get("nickname")
            if u and d:
                mapping[u] = d

    return mapping


def save_mapping(mapping, path=MAPPING_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    return path


def load_mapping(path=MAPPING_FILE):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def resolve_display_name(wxid, mapping=None):
    """wxid -> 显示名。找不到时原样返回 wxid（ChatWith 会失败，需兜底处理）。"""
    if mapping is None:
        mapping = load_mapping()
    return mapping.get(wxid, wxid)


def classify(wxid):
    """判断会话类型：'filehelper' / 'group' / 'openim'(企业客服) / 'private' / 'other'。"""
    if wxid == "filehelper":
        return "filehelper"
    if wxid.endswith("@chatroom"):
        return "group"
    if wxid.endswith("@openim"):
        return "openim"
    if wxid.startswith("wxid_"):
        return "private"
    return "other"


if __name__ == "__main__":
    m = fetch_mapping()
    path = save_mapping(m)
    print(f"映射已保存: {path}")
    print(f"总条目: {len(m)}")
    samples = [k for k in m if k.startswith("wxid_")][:5]
    groups = [k for k in m if k.endswith("@chatroom")][:3]
    print("私聊样例:")
    for k in samples:
        print(f"  {k} -> {m[k]}")
    print("群聊样例:")
    for k in groups:
        print(f"  {k} -> {m[k]}")
    print("文件传输助手:", m.get("filehelper"))
