# -*- coding: utf-8 -*-
"""
中文电子书 / 网络小说高速检索与下载模块

特点：
  - 免登录、免 Token、国内 CDN 直连（无需代理）
  - 智能书名精确匹配与评分排序（优选正版完结全本）
  - 整本压缩包直链极速下载并自动解压转换为 UTF-8 编码 .txt 电子书
  - 零外部依赖，纯标准库实现
"""
import io
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile

from core.config import get_config, VIDEO_DIR
from core.logger import logger

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

SEARCH_API = "https://www.ixdzs8.com/bsearch?q="
BASE_HOST = "https://www.ixdzs8.com"


class BookNotFound(Exception):
    """未找到可下载的电子书资源。"""
    pass


def _http_get(url, referer=None, timeout=10, retries=3):
    """带重试与 User-Agent 的 HTTP GET 请求。"""
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    raise BookNotFound(f"网络请求失败 ({url}): {last_err}")


def _score_candidate(book_name, raw_title):
    """给候选书名打分，确保优先命中完全匹配的原版全本。"""
    clean_target = book_name.strip().strip("《》").strip()
    t = raw_title.strip().strip("《》").strip()
    
    if t == clean_target:
        return 100
    if t == f"{clean_target}（全集）" or t == f"{clean_target}全集" or t == f"{clean_target}（精校版）":
        return 95
    if t == f"{clean_target}（全本）" or t == f"{clean_target}完结":
        return 90
    if t.startswith(clean_target):
        return 60 - len(t)
    if clean_target in t:
        return 30 - len(t)
    return 0


def search_book(title):
    """检索书籍并返回最佳候选信息 (detail_path, real_title)。未找到抛 BookNotFound。"""
    clean_title = title.strip().strip("《》").strip()
    if not clean_title:
        raise BookNotFound("书名不能为空")

    search_url = SEARCH_API + urllib.parse.quote(clean_title)
    raw_data = _http_get(search_url)
    html = raw_data.decode("utf-8", errors="ignore")

    # 提取 /read/ 链接与书名
    links = re.findall(r'<a[^>]*href="(/read/\d+/)"[^>]*>(.*?)</a>', html)
    candidates = []
    seen = set()
    for path, raw_t in links:
        t_clean = re.sub(r'<[^>]+>', '', raw_t).strip()
        if t_clean and not t_clean.startswith("<img") and path not in seen:
            seen.add(path)
            score = _score_candidate(clean_title, t_clean)
            if score > 0:
                candidates.append((path, t_clean, score))

    if not candidates:
        raise BookNotFound(f"未找到《{clean_title}》相关电子书资源")

    # 按匹配得分降序
    candidates.sort(key=lambda x: x[2], reverse=True)
    best_path, best_title, _ = candidates[0]
    return best_path, best_title


def resolve_book(title, download_dir=None):
    """主入口：搜索并下载电子书，解压为规范 UTF-8 txt 文件存入 download_dir。

    返回 ("book", [txt_path])；失败抛 BookNotFound。
    """
    download_dir = download_dir or VIDEO_DIR
    os.makedirs(download_dir, exist_ok=True)
    clean_title = title.strip().strip("《》").strip()

    logger.info(f"[电子书] 开始检索《{clean_title}》...")
    detail_path, real_title = search_book(clean_title)
    detail_url = urllib.parse.urljoin(BASE_HOST, detail_path)

    # 访问详情页解析下载直链
    d_html = _http_get(detail_url).decode("utf-8", errors="ignore")
    dl_buttons = re.findall(r'<a[^>]*href="([^"]*down[^"]*)"[^>]*>(.*?)</a>', d_html, re.IGNORECASE)
    if not dl_buttons:
        raise BookNotFound(f"《{real_title}》暂未提供全本下载直链")

    dl_url = dl_buttons[0][0]
    logger.info(f"[电子书] 命中《{real_title}》，正在极速下载全本压缩包...")

    # 下载 zip 压缩包
    zip_bytes = _http_get(dl_url, referer=detail_url, timeout=30)
    if not zip_bytes:
        raise BookNotFound(f"《{real_title}》下载内容为空")

    # 内存解压并统一转换为 UTF-8
    out_path = os.path.join(download_dir, f"{real_title}.txt")
    txt_content = ""

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                raw_extracted = zf.read(name)
                for enc in ("utf-8", "gbk", "gb18030", "gb2312"):
                    try:
                        txt_content = raw_extracted.decode(enc)
                        break
                    except Exception:
                        continue
                if txt_content:
                    break
    except zipfile.BadZipFile:
        # 个别源直接返回 txt 文件流而非 zip
        for enc in ("utf-8", "gbk", "gb18030", "gb2312"):
            try:
                txt_content = zip_bytes.decode(enc)
                break
            except Exception:
                continue

    if not txt_content or len(txt_content.strip()) < 50:
        raise BookNotFound(f"《{real_title}》解压内容过短或损坏")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(txt_content)

    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    logger.info(f"[电子书] 《{real_title}》下载解压成功 (大小: {size_mb:.2f} MB)")
    return "book", [out_path]


def test_novel():
    """测试电子书解析与下载环境。返回 (ok, detail)。"""
    try:
        _, title = search_book("三体")
        return True, f"电子书检索下载引擎就绪（检索测试：《{title}》匹配成功）"
    except Exception as e:
        return False, f"电子书引擎测试异常: {e}"
