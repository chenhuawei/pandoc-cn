#!/usr/bin/env python3
"""用 LibreOffice 的 PDF 分页结果回填 DOCX 目录页码。"""

import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from fix_docx import build_name_to_id, extract_headings

SOFFICE = os.environ.get(
    "SOFFICE", "/Applications/LibreOffice.app/Contents/MacOS/soffice"
)

PDFKIT_OUTLINE_SCRIPT = r"""
ObjC.import('Quartz');
ObjC.import('Foundation');
function run(argv) {
    const pdf = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
    if (!pdf) { throw new Error('cannot open PDF'); }
    const entries = [];
    function walk(node, depth) {
        for (let i = 0; i < node.numberOfChildren; i++) {
            const item = node.childAtIndex(i);
            const destination = item.destination;
            if (depth < 3 && destination) {
                const page = destination.page;
                if (page) {
                    entries.push({
                        label: item.label.js,
                        page: Number(pdf.indexForPage(page)) + 1
                    });
                }
            }
            walk(item, depth + 1);
        }
    }
    const root = pdf.outlineRoot;
    if (root) { walk(root, 0); }
    return JSON.stringify(entries);
}
"""


def export_pdf(path, workdir):
    output_dir = workdir / "pdf"
    profile = workdir / "profile"
    output_dir.mkdir()
    try:
        result = subprocess.run(
            [
                SOFFICE,
                "--headless",
                "--norestore",
                "--nologo",
                f"-env:UserInstallation={profile.as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("LibreOffice 导出 PDF 超时（300 秒）") from exc
    pdf_path = output_dir / f"{path.stem}.pdf"
    if result.returncode != 0 or not pdf_path.is_file():
        raise RuntimeError(
            f"LibreOffice 导出 PDF 失败：{result.stdout}{result.stderr}".strip()
        )
    return pdf_path


def read_pdf_outline(pdf_path):
    if sys.platform != "darwin":
        import pymupdf
        with pymupdf.open(pdf_path) as pdf:
            return [
                {"label": title, "page": page}
                for level, title, page in pdf.get_toc()
                if level <= 3
            ]
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-", str(pdf_path)],
        input=PDFKIT_OUTLINE_SCRIPT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"macOS PDFKit 读取大纲失败：{result.stderr.strip()}")
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法解析 PDF 大纲：{result.stdout}") from exc


def heading_page_map(document, styles, outline):
    _, name_to_id = build_name_to_id(styles)
    headings = extract_headings(document, name_to_id)
    if not headings:
        return {}
    if len(headings) != len(outline):
        raise RuntimeError(
            f"PDF 大纲条目数（{len(outline)}）与 DOCX 目录条目数（{len(headings)}）不一致"
        )

    pages = {}
    for (_, anchor, raw_text), item in zip(headings, outline):
        text = html.unescape(raw_text).strip()
        label = item["label"].strip()
        prefix = label[:-len(text)] if text and label.endswith(text) else None
        if label != text and (prefix is None or not re.fullmatch(
                r"\d+(?:\.\d+)*\s+", prefix)):
            raise RuntimeError(f"PDF 大纲标题 {label!r} 与 DOCX 标题 {text!r} 不一致")
        page = item["page"]
        if not isinstance(page, int) or page < 1:
            raise RuntimeError(f"标题 {text!r} 的 PDF 页码无效：{page!r}")
        pages[anchor] = page
    return pages


def fill_page_numbers(document, pages):
    toc_match = re.search(r"<w:sdt>.*?</w:sdt>", document, re.S)
    if not toc_match:
        raise RuntimeError("DOCX 中未找到目录内容控件")
    updated_count = 0

    def update_paragraph(paragraph_match):
        nonlocal updated_count
        paragraph = paragraph_match.group(0)
        instruction = re.search(
            r"<w:instrText[^>]*>\s*PAGEREF\s+([^\s<]+)", paragraph
        )
        if not instruction:
            return paragraph
        anchor = instruction.group(1)
        if anchor not in pages:
            raise RuntimeError(f"目录锚点 {anchor!r} 没有对应 PDF 页码")
        separate = re.search(
            r'<w:fldChar[^>]*w:fldCharType="separate"[^>]*/>',
            paragraph[instruction.end():],
        )
        if not separate:
            raise RuntimeError(f"目录锚点 {anchor!r} 的 PAGEREF 域不完整")
        cached_start = instruction.end() + separate.end()
        cached = re.search(
            r"<w:t(?:\s[^>]*)?>[^<]*</w:t>|<w:t\s*/>", paragraph[cached_start:]
        )
        if not cached:
            raise RuntimeError(f"目录锚点 {anchor!r} 缺少页码缓存节点")
        start = cached_start + cached.start()
        end = cached_start + cached.end()
        updated_count += 1
        return paragraph[:start] + f"<w:t>{pages[anchor]}</w:t>" + paragraph[end:]

    toc = re.sub(
        r"<w:p\b.*?</w:p>", update_paragraph, toc_match.group(0), flags=re.S
    )
    if updated_count != len(pages):
        raise RuntimeError(
            f"已回填 {updated_count} 个页码，但应有 {len(pages)} 个"
        )
    return document[:toc_match.start()] + toc + document[toc_match.end():]


def verify_page_numbers(path, expected_count):
    with zipfile.ZipFile(path) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    toc = re.search(r"<w:sdt>.*?</w:sdt>", document, re.S).group(0)
    page_numbers = []
    for paragraph in re.findall(r"<w:p\b.*?</w:p>", toc, re.S):
        instruction = re.search(
            r"<w:instrText[^>]*>\s*PAGEREF\b.*?</w:instrText>", paragraph, re.S
        )
        if not instruction:
            continue
        separate = re.search(
            r'<w:fldChar[^>]*w:fldCharType="separate"[^>]*/>',
            paragraph[instruction.end():],
        )
        cached = re.search(
            r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>",
            paragraph[instruction.end() + separate.end():],
        )
        number = cached.group(1) if cached else ""
        if not re.fullmatch(r"\d+", number):
            raise RuntimeError("目录页码校验失败：缓存仍为空或不是数字")
        page_numbers.append(number)
    if len(page_numbers) != expected_count:
        raise RuntimeError("目录页码校验失败：条目数量不一致")
    return page_numbers


def update_toc(path):
    with zipfile.ZipFile(path) as archive:
        order = archive.infolist()
        entries = {info.filename: archive.read(info.filename) for info in order}
    document = entries["word/document.xml"].decode("utf-8")
    styles = entries["word/styles.xml"].decode("utf-8")

    with tempfile.TemporaryDirectory(prefix="markdown-to-docx-") as tempdir:
        pdf_path = export_pdf(path, Path(tempdir))
        outline = read_pdf_outline(pdf_path)
    pages = heading_page_map(document, styles, outline)
    if not pages:
        print(f"toc skipped: {path} (no headings)")
        return
    entries["word/document.xml"] = fill_page_numbers(document, pages).encode("utf-8")

    temp_path = path.with_name(f".{path.name}.toc-tmp")
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for info in order:
                archive.writestr(info, entries[info.filename])
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    page_numbers = verify_page_numbers(path, len(pages))
    print(f"toc updated: {path} (pages: {', '.join(page_numbers)})")


def main(paths):
    if not os.path.isfile(SOFFICE):
        sys.stderr.write(
            "update_toc: 未找到 LibreOffice（%s），跳过目录页码更新；"
            "可在 WPS 中 Ctrl+A 后按 F9 手动更新\n" % SOFFICE
        )
        raise SystemExit(2)
    if sys.platform == "darwin" and not shutil.which("osascript"):
        raise SystemExit("update_toc: 未找到 macOS osascript/PDFKit 运行环境")
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"update_toc: 文件不存在：{path}")
        update_toc(path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 update_toc.py <file.docx> [...]")
    try:
        main(sys.argv[1:])
    except Exception as exc:
        raise SystemExit(f"update_toc: {exc}")
