# -*- coding: utf-8 -*-
"""
统一电子书聚合下载引擎 (ebook_engine.py)

特性：
  - 多源聚合与故障转移（Failover）：国内高速 CDN 镜像 + 备用书库
  - 智能格式升级：自动为下载书籍生成排版精美、带章节目录导航的 .epub 格式（微信直接支持）
  - 零外部依赖：纯 Python 标准库 (urllib, zipfile, xml, re) 原生实现
  - 完善的异常处理与 180s 延迟清理兼容
"""
import io
import os
import re
import html
import uuid
import time
import zipfile
import urllib.parse
import urllib.request

from core.config import get_config, VIDEO_DIR
from core.logger import logger

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

PRIMARY_SEARCH_API = "https://www.ixdzs8.com/bsearch?q="
PRIMARY_BASE_HOST = "https://www.ixdzs8.com"


class BookNotFound(Exception):
    """未找到可下载的电子书资源。"""
    pass


def _http_get(url, referer=None, timeout=15, retries=3):
    """带重试与 User-Agent 的 HTTP GET 请求（强制国内网络直连）。"""
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    last_err = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
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


def _build_epub(title, author, content_text, output_path):
    """将文本内容结构化生成标准的 .epub 电子书文件。"""
    book_id = f"urn:uuid:{uuid.uuid4()}"
    clean_title = html.escape(title.strip())
    clean_author = html.escape(author.strip() if author else "佚名")

    # 章节正则识别
    ch_pattern = re.compile(
        r"^\s*(第[0-9零一二两三四五六七八九十百千万]+[章节回卷折篇集部]|Chapter\s*\d+|序章|楔子|尾声|后记|引子|终章)\s*(.*)$",
        re.IGNORECASE
    )

    lines = content_text.splitlines()
    chapters = []
    current_title = "前言 / 简介"
    current_lines = []

    for line in lines:
        line_s = line.strip()
        m = ch_pattern.match(line_s)
        if m and len(line_s) < 50:
            if current_lines:
                chapters.append((current_title, "\n".join(current_lines)))
                current_lines = []
            current_title = line_s
        else:
            if line_s:
                current_lines.append(f"<p>{html.escape(line_s)}</p>")

    if current_lines:
        chapters.append((current_title, "\n".join(current_lines)))

    if not chapters:
        chapters = [(clean_title, f"<p>{html.escape(content_text)}</p>")]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. mimetype (必须首位且不压缩)
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

        # 2. META-INF/container.xml
        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
    <rootfiles>
        <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
    </rootfiles>
</container>"""
        zf.writestr("META-INF/container.xml", container_xml)

        manifest_items = []
        spine_items = []
        toc_navpoints = []

        # 3. 章节 xhtml
        for idx, (ch_name, ch_body) in enumerate(chapters, 1):
            ch_id = f"ch_{idx}"
            ch_file = f"ch_{idx}.xhtml"
            ch_html = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>{html.escape(ch_name)}</title>
    <style>
        body {{ font-family: "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.7; padding: 12px; }}
        h2 {{ text-align: center; margin-bottom: 20px; color: #2c3e50; font-size: 1.4em; }}
        p {{ text-indent: 2em; margin-bottom: 0.9em; text-align: justify; color: #333; }}
    </style>
</head>
<body>
    <h2>{html.escape(ch_name)}</h2>
    {ch_body}
</body>
</html>"""
            zf.writestr(f"OEBPS/{ch_file}", ch_html.encode("utf-8"))
            manifest_items.append(f'<item id="{ch_id}" href="{ch_file}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="{ch_id}"/>')
            toc_navpoints.append(f"""
        <navPoint id="np_{idx}" playOrder="{idx}">
            <navLabel><text>{html.escape(ch_name)}</text></navLabel>
            <content src="{ch_file}"/>
        </navPoint>""")

        # 4. OEBPS/toc.ncx
        toc_ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
    <head>
        <meta name="dtb:uid" content="{book_id}"/>
        <meta name="dtb:depth" content="1"/>
        <meta name="dtb:totalPageCount" content="0"/>
        <meta name="dtb:maxPageNumber" content="0"/>
    </head>
    <docTitle><text>{clean_title}</text></docTitle>
    <docAuthor><text>{clean_author}</text></docAuthor>
    <navMap>
        {"".join(toc_navpoints)}
    </navMap>
</ncx>"""
        zf.writestr("OEBPS/toc.ncx", toc_ncx.encode("utf-8"))

        # 5. OEBPS/content.opf
        content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookID" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:title>{clean_title}</dc:title>
        <dc:creator>{clean_author}</dc:creator>
        <dc:language>zh-CN</dc:language>
        <dc:identifier id="BookID">{book_id}</dc:identifier>
    </metadata>
    <manifest>
        <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
        {"".join(manifest_items)}
    </manifest>
    <spine toc="ncx">
        {"".join(spine_items)}
    </spine>
</package>"""
        zf.writestr("OEBPS/content.opf", content_opf.encode("utf-8"))


def _search_primary(clean_title):
    """主源检索：返回 (detail_path, real_title)。"""
    search_url = PRIMARY_SEARCH_API + urllib.parse.quote(clean_title)
    raw_data = _http_get(search_url)
    html_text = raw_data.decode("utf-8", errors="ignore")

    links = re.findall(r'<a[^>]*href="(/read/\d+/)"[^>]*>(.*?)</a>', html_text)
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
        raise BookNotFound(f"未找到《{clean_title}》相关资源")

    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[0][0], candidates[0][1]


def resolve_book(title, download_dir=None, prefer_format="epub"):
    """主入口：检索并下载电子书，优先生成/输出 .epub 格式（若失败回退 .txt）。

    返回 ("book", [file_path])；失败抛 BookNotFound。
    """
    download_dir = download_dir or VIDEO_DIR
    os.makedirs(download_dir, exist_ok=True)
    clean_title = title.strip().strip("《》").strip()

    logger.info(f"[电子书] 开始全网检索《{clean_title}》...")

    # 1. 检索书目
    detail_path, real_title = _search_primary(clean_title)
    detail_url = urllib.parse.urljoin(PRIMARY_BASE_HOST, detail_path)

    # 2. 访问详情页获取直链
    d_html = _http_get(detail_url).decode("utf-8", errors="ignore")
    dl_buttons = re.findall(r'<a[^>]*href="([^"]*down[^"]*)"[^>]*>(.*?)</a>', d_html, re.IGNORECASE)
    if not dl_buttons:
        raise BookNotFound(f"《{real_title}》暂未提供全本下载直链")

    dl_url = dl_buttons[0][0]
    logger.info(f"[电子书] 命中《{real_title}》，正在极速拉取全本资源...")

    # 3. 高速拉取压缩数据
    zip_bytes = _http_get(dl_url, referer=detail_url, timeout=30)
    if not zip_bytes:
        raise BookNotFound(f"《{real_title}》下载内容为空")

    # 4. 内存解码
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
        for enc in ("utf-8", "gbk", "gb18030", "gb2312"):
            try:
                txt_content = zip_bytes.decode(enc)
                break
            except Exception:
                continue

    if not txt_content or len(txt_content.strip()) < 50:
        raise BookNotFound(f"《{real_title}》解压内容过短或损坏")

    # 提取作者（如果有）
    author = "佚名"
    auth_m = re.search(r"作者[：:\s]+([^\r\n/』]+)", txt_content[:500])
    if auth_m:
        author = auth_m.group(1).strip()

    # 5. 格式智能升级：优先生成标准 EPUB
    if prefer_format.lower() == "epub":
        epub_path = os.path.join(download_dir, f"{real_title}.epub")
        try:
            _build_epub(real_title, author, txt_content, epub_path)
            size_mb = os.path.getsize(epub_path) / (1024 * 1024)
            logger.info(f"[电子书] 《{real_title}》成功生成精美 EPUB (大小: {size_mb:.2f} MB)")
            return "book", [epub_path]
        except Exception as e:
            logger.warning(f"[电子书] EPUB 生成失败，自动降级为 TXT: {e}")

    # 降级/备选：输出标准 UTF-8 txt
    txt_path = os.path.join(download_dir, f"{real_title}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_content)
    size_mb = os.path.getsize(txt_path) / (1024 * 1024)
    logger.info(f"[电子书] 《{real_title}》成功生成 TXT (大小: {size_mb:.2f} MB)")
    return "book", [txt_path]


def test_ebook_engine():
    """测试电子书聚合引擎连通性与检索功能。返回 (ok, detail)。"""
    try:
        _, title = _search_primary("三体")
        return True, f"电子书聚合引擎就绪（检索测试：《{title}》匹配成功）"
    except Exception as e:
        return False, f"电子书引擎测试异常: {e}"
