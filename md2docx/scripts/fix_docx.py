#!/usr/bin/env python3
"""pandoc docx 后处理脚本（配合 WPS 制作的 template.docx 使用）

解决五个问题：
1. 目录打开后空白：pandoc 生成的 TOC 域结构畸形（fldChar/instrText 挤在
   同一个 run 内）且无缓存内容，WPS/预览不渲染也不更新。
   本脚本重建为标准多 run 域结构，并把标题条目 + PAGEREF 域烘焙为缓存
   内容——任何环境打开立即可见，打开后页码自动刷新。
2. 目录页码不自动更新：向 settings.xml 注入 <w:updateFields w:val="true"/>。
3. 封面标题/表格样式丢失：template.docx 由 WPS 生成，样式 styleId 为数字
   （如 Title=19、Table=30），而 pandoc 按样式名引用（w:pStyle w:val="Title"），
   WPS 无法解析导致回退为正文格式。按 styles.xml 的“样式名 -> styleId”
   映射修正 document.xml 中的引用。
4. 表格列宽失衡：pandoc 按 markdown 源码字符宽度分配列宽，填充过空格
   的列（如“备注”）会吃掉大半宽度。本脚本按单元格实际内容（CJK 计 2 宽）
   重算各列比例，带每列下限/上限，重写 tblGrid。
5. 封面、修订记录、目录顺序错乱或之间无分页：重排封面与修订记录，
   并在封面最后一个元数据段落后、修订记录块后和目录（sdt 块）后补分页符。

用法：python3 fix_docx.py <file.docx> [more.docx ...]
仅依赖 Python 标准库。
"""

import re
import shutil
import sys
import zipfile

PAGE_BREAK = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'

# 表格列宽约束（占总宽比例）
COL_MIN_SHARE = 0.07
COL_MAX_SHARE = 0.38


# ---------------------------------------------------------------- 样式映射
def build_name_to_id(styles_xml):
    """从 styles.xml 提取 样式名 -> styleId 映射。"""
    ids = set(re.findall(r'w:styleId="([^"]+)"', styles_xml))
    name2id = {}
    pattern = re.compile(
        r'<w:style\b[^>]*w:styleId="([^"]+)"[^>]*>'
        r'(?:(?!</w:style>).)*?<w:name w:val="([^"]+)"',
        re.S,
    )
    for m in pattern.finditer(styles_xml):
        name2id.setdefault(m.group(2), m.group(1))
    return ids, name2id


def remap_style_refs(doc_xml, ids, name2id):
    """把 document.xml 中按样式名引用的 pStyle/rStyle/tblStyle 改成 styleId。"""

    def repl(m):
        attr, val = m.group(1), m.group(2)
        if val not in ids and val in name2id:
            return attr + name2id[val] + '"'
        return m.group(0)

    return re.sub(
        r'(<w:(?:pStyle|rStyle|tblStyle) w:val=")([^"]+)"', repl, doc_xml
    )


# ------------------------------------------------- 修订记录：移位 + 目录排除

def get_style_formatting(styles_xml, style_id):
    """取指定样式的段落/字符格式定义（pPr/rPr 子元素，去掉 pStyle/numPr/outlineLvl）。"""
    m = re.search(
        r'<w:style\b[^>]*w:styleId="%s"[^>]*>(?:(?!</w:style>).)*</w:style>'
        % re.escape(style_id), styles_xml, re.S)
    if not m:
        return '', ''
    ppr_m = re.search(r'<w:pPr>(.*?)</w:pPr>', m.group(0), re.S)
    rpr_m = re.search(r'<w:rPr>(.*?)</w:rPr>', m.group(0), re.S)
    ppr = ppr_m.group(1) if ppr_m else ''
    rpr = rpr_m.group(1) if rpr_m else ''
    # 去掉大纲/编号相关，避免被目录收录或参与标题自动编号
    for tag in ('w:pStyle', 'w:numPr', 'w:outlineLvl'):
        ppr = re.sub(r'<%s\b.*?</%s>|<%s\b[^>]*/>' % (tag, tag, tag), '', ppr,
                     flags=re.S)
    return ppr, rpr


def styled_paragraphs(doc_xml, include_unstyled=False):
    pattern = re.compile(
        r'((?:<w:bookmarkStart\b[^>]*/>\s*)*)'
        r'(<w:p>(?:(?!</w:p>).)*?</w:p>)', re.S)
    for match in pattern.finditer(doc_xml):
        style = re.search(r'<w:pStyle w:val="([^"]+)"', match.group(2))
        if style or include_unstyled:
            yield match, style.group(1) if style else ''


def paragraph_text(paragraph):
    return ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', paragraph))


def is_revision_title(paragraph, title='修订记录'):
    text = paragraph_text(paragraph).strip()
    return text in (title, '文档' + title)


def block_end(doc_xml, paragraph_end):
    bookmark_end = re.match(
        r'\s*<w:bookmarkEnd\b[^>]*/>', doc_xml[paragraph_end:paragraph_end + 200])
    return paragraph_end + (bookmark_end.end() if bookmark_end else 0)


def move_cover(doc_xml, name2id):
    """把封面元数据块移到开头，兼容正文标题加文档信息表的封面。"""
    title_id = name2id.get('Title')
    if not title_id:
        return doc_xml
    cover_ids = {
        name2id[name]
        for name in ('Title', 'Subtitle', 'Author', 'Date')
        if name in name2id
    }
    paragraphs = list(styled_paragraphs(doc_xml, include_unstyled=True))
    cover = [(match, style) for match, style in paragraphs if style in cover_ids]
    selected = []
    if any(style == title_id for _, style in cover):
        selected = [match for match, _ in cover]
    else:
        h1 = name2id.get('heading 1')
        toc = re.search(r'<w:sdt>.*?</w:sdt>', doc_xml, re.S)
        revision = next((
            match for match, _ in paragraphs
            if toc and match.start() >= toc.end()
            and is_revision_title(match.group(2))
        ), None)
        if h1 and revision:
            candidates = [
                match for match, style in paragraphs
                if toc.end() <= match.start() < revision.start() and style == h1
            ]
            if len(candidates) == 1:
                match = candidates[0]
                para = re.sub(
                    r'<w:pStyle w:val="%s"([^>]*)/>' % re.escape(h1),
                    r'<w:pStyle w:val="%s"\1/>' % title_id,
                    match.group(2), count=1)
                end = block_end(doc_xml, match.end())
                while True:
                    table = re.match(
                        r'\s*<w:tbl>.*?</w:tbl>', doc_xml[end:], re.S)
                    if not table:
                        break
                    end += table.end()
                block = match.group(1) + para + doc_xml[match.end():end]
                doc_xml = doc_xml[:match.start()] + doc_xml[end:]
                body_start = doc_xml.find('<w:body>') + len('<w:body>')
                return doc_xml[:body_start] + block + doc_xml[body_start:]
    if not selected:
        return doc_xml

    blocks = [(match.start(), block_end(doc_xml, match.end())) for match in selected]
    block = ''.join(doc_xml[start:end] for start, end in blocks)
    for start, end in reversed(blocks):
        doc_xml = doc_xml[:start] + doc_xml[end:]
    body_start = doc_xml.find('<w:body>') + len('<w:body>')
    return doc_xml[:body_start] + block + doc_xml[body_start:]


def move_revision_history(doc_xml, styles_xml, name2id, title='修订记录'):
    """把修订记录标题及表格移到目录前，并取消其大纲级别。"""
    h1 = name2id.get('heading 1')
    if not h1:
        return doc_xml
    m = next((
        match for match, _ in styled_paragraphs(doc_xml, include_unstyled=True)
        if is_revision_title(match.group(2), title)
    ), None)
    if not m:
        return doc_xml
    # 紧随其后可能有 bookmarkEnd 和表格
    pos = m.end()
    tail = doc_xml[pos:pos + 200]
    bm_end = re.match(r'\s*(<w:bookmarkEnd\b[^>]*/>)', tail)
    extra = bm_end.group(1) if bm_end else ''
    pos2 = pos + (bm_end.end() if bm_end else 0)
    tbl_m = re.match(r'\s*(<w:tbl>.*?</w:tbl>)', doc_xml[pos2:], re.S)
    table = tbl_m.group(1) if tbl_m else ''
    cut_end = pos2 + (tbl_m.end() if tbl_m else 0)

    # 外观沿用 Heading 1，但不再是大纲标题，目录不会收录。
    ppr_fmt, rpr_fmt = get_style_formatting(styles_xml, h1)
    para = m.group(2)
    para = re.sub(r'<w:pStyle w:val="[^"]+"[^>]*/>', '', para, count=1)
    if ppr_fmt:
        para = para.replace('<w:pPr>', '<w:pPr>' + ppr_fmt, 1)
    if rpr_fmt:
        # 已有 rPr 的 run：样式属性注入到最前（后续直接属性仍可覆盖）
        para = para.replace('<w:r><w:rPr>', '<w:r><w:rPr>' + rpr_fmt)
        # 没有 rPr 的 run：补一个
        para = re.sub(r'(<w:r>)(?!<w:rPr>)', r'\1<w:rPr>' + rpr_fmt + '</w:rPr>',
                      para)

    block = m.group(1) + para + extra + table + PAGE_BREAK
    doc_xml = doc_xml[:m.start()] + doc_xml[cut_end:]
    # 插到目录 sdt 之前
    sdt_i = doc_xml.find('<w:sdt>')
    if sdt_i < 0:
        return doc_xml[:m.start()] + block + doc_xml[m.start():]
    return doc_xml[:sdt_i] + block + doc_xml[sdt_i:]


# ---------------------------------------------------------------- 目录烘焙

def xml_escape(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


def extract_headings(doc_xml, name2id):
    """提取 1-3 级标题：[(level, bookmark_anchor, text)]"""
    h_ids = {}
    for level in (1, 2, 3):
        sid = name2id.get('heading %d' % level)
        if sid:
            h_ids[sid] = level
    headings = []
    for bm in re.finditer(
            r'<w:bookmarkStart\b[^>]*w:name="([^"]+)"[^>]*/>', doc_xml):
        anchor = bm.group(1)
        # 在书签后查找紧随的标题段落
        seg = doc_xml[bm.end():bm.end() + 3000]
        pm = re.search(r'<w:p>.*?</w:p>', seg, re.S)
        if not pm:
            continue
        para = pm.group(0)
        sm = re.search(r'<w:pStyle w:val="([^"]+)"', para)
        if not sm or sm.group(1) not in h_ids:
            continue
        text = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', para))
        if text:
            headings.append((h_ids[sm.group(1)], anchor, text))
    return headings


def content_width(doc_xml):
    """版心宽度 = 页宽 - 左右边距（twips）。"""
    sz = re.search(r'<w:pgSz\b[^>]*w:w="(\d+)"', doc_xml)
    mar = re.search(r'<w:pgMar\b[^>]*>', doc_xml)
    page = int(sz.group(1)) if sz else 11906
    left = right = 1800
    if mar:
        lm = re.search(r'w:left="(\d+)"', mar.group(0))
        rm = re.search(r'w:right="(\d+)"', mar.group(0))
        if lm:
            left = int(lm.group(1))
        if rm:
            right = int(rm.group(1))
    return page - left - right


def build_toc_sdt(doc_xml, name2id):
    """把 pandoc 的畸形空 TOC 域重建为带缓存条目的标准域结构。"""
    m = re.search(r'<w:sdt>.*?</w:sdt>', doc_xml, re.S)
    if not m:
        return doc_xml
    sdt = m.group(0)
    headings = extract_headings(doc_xml, name2id)
    if not headings:
        return doc_xml

    sdt_pr = re.search(r'<w:sdtPr>.*?</w:sdtPr>', sdt, re.S)
    heading_para = re.search(r'<w:p>.*?</w:p>', sdt, re.S)  # “目录”标题段
    pos = content_width(doc_xml)
    toc_styles = {lv: name2id.get('toc %d' % lv, '') for lv in (1, 2, 3)}

    field_begin = (
        '<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
        '<w:r><w:instrText xml:space="preserve">'
        ' TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    )
    field_end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'

    paras = []
    for idx, (level, anchor, text) in enumerate(headings):
        # pandoc 会裁剪未使用的样式，toc 1/2/3 可能不存在，存在才引用
        style = toc_styles.get(level) or toc_styles.get(1) or ''
        pstyle = '<w:pStyle w:val="%s"/>' % style if style else ''
        # 层级缩进：模板的 toc 1/2/3 样式未定义缩进，在段落级显式指定
        indent = (level - 1) * 420
        ppr = ('<w:pPr>%s'
               '<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="%d"/>'
               '</w:tabs><w:ind w:left="%d"/></w:pPr>') % (pstyle, pos, indent)
        entry = (
            '<w:hyperlink w:anchor="%s">'
            '<w:r><w:rPr><w:rFonts w:hint="eastAsia"/></w:rPr>'
            '<w:t xml:space="preserve">%s</w:t></w:r>'
            '<w:r><w:tab/></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
            '<w:r><w:instrText xml:space="preserve">'
            ' PAGEREF %s \\h </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t/></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '</w:hyperlink>'
        ) % (anchor, xml_escape(text), anchor)
        prefix = field_begin if idx == 0 else ''
        suffix = field_end if idx == len(headings) - 1 else ''
        paras.append('<w:p>%s%s%s%s</w:p>' % (ppr, prefix, entry, suffix))

    new_sdt = ('<w:sdt>%s<w:sdtContent>%s%s</w:sdtContent></w:sdt>'
               % (sdt_pr.group(0) if sdt_pr else '',
                  heading_para.group(0) if heading_para else '',
                  ''.join(paras)))
    return doc_xml[:m.start()] + new_sdt + doc_xml[m.end():]


def enable_update_fields(settings_xml):
    """注入 updateFields，使打开文档时自动更新目录等域。

    注意：OOXML 对 w:settings 的子元素顺序有严格 schema 要求，
    updateFields 必须位于 footnotePr/endnotePr/compat 之前，
    插到开头会被 WPS 直接忽略（Word 有时容忍）。
    """
    if 'w:updateFields' in settings_xml:
        return settings_xml
    for anchor in ('<w:footnotePr>', '<w:endnotePr>', '<w:compat>',
                   '<w:rsids>', '</w:settings>'):
        if anchor in settings_xml:
            return settings_xml.replace(
                anchor, '<w:updateFields w:val="true"/>' + anchor, 1)
    return settings_xml


# ---------------------------------------------------------------- 表格列宽

def display_width(text):
    """显示宽度：CJK 等宽字符计 2，其余计 1。"""
    return sum(2 if ord(c) > 0x2E7F else 1 for c in text)


def rebalance_shares(raw, lo=COL_MIN_SHARE, hi=COL_MAX_SHARE):
    """按比例分配份额，带上下限；被截断的份额按比例转给未受限列。"""
    total = sum(raw) or 1
    shares = [w / total for w in raw]
    for _ in range(10):
        clamped = [i for i, s in enumerate(shares) if s <= lo or s >= hi]
        if not clamped:
            break
        free = [i for i in range(len(shares)) if i not in clamped]
        # 被截列释放的份额为正、被抬升列消耗的份额为负，净额在自由列间分配
        extra = 0.0
        for i in clamped:
            if shares[i] <= lo:
                extra += shares[i] - lo
                shares[i] = lo
            else:
                extra += shares[i] - hi
                shares[i] = hi
        pool = sum(raw[i] for i in free)
        if abs(extra) <= 1e-9 or pool <= 1e-9:
            break
        for i in free:
            shares[i] += extra * (raw[i] / pool)
    return shares


def fix_table_widths(doc_xml):
    """按单元格实际内容重算每张表的列宽，重写 tblGrid。"""

    def fix_tbl(m):
        tbl = m.group(0)
        grid_m = re.search(r'<w:tblGrid>(.*?)</w:tblGrid>', tbl, re.S)
        if not grid_m:
            return tbl
        widths = [int(w) for w in
                  re.findall(r'<w:gridCol w:w="(\d+)"', grid_m.group(1))]
        ncols = len(widths)
        if ncols < 2:
            return tbl

        maxw = [1] * ncols
        for row in re.findall(r'<w:tr\b.*?</w:tr>', tbl, re.S):
            cells = re.findall(r'<w:tc>.*?</w:tc>', row, re.S)
            for i, cell in enumerate(cells[:ncols]):
                text = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', cell))
                w = display_width(text)
                if w > maxw[i]:
                    maxw[i] = w

        shares = rebalance_shares(maxw)
        total = sum(widths)
        new_widths = [max(1, round(s * total)) for s in shares]
        # 舍入误差交给最宽列吸收
        drift = total - sum(new_widths)
        widest = new_widths.index(max(new_widths))
        new_widths[widest] += drift

        new_grid = '<w:tblGrid>%s</w:tblGrid>' % ''.join(
            '<w:gridCol w:w="%d" />' % w for w in new_widths)
        tbl = tbl[:grid_m.start()] + new_grid + tbl[grid_m.end():]
        # 删除单元格级 tcW，避免与 gridCol 冲突（fixed 布局以 gridCol 为准）
        tbl = re.sub(r'<w:tcW\b[^>]*/>', '', tbl)
        return tbl

    return re.sub(r'<w:tbl>.*?</w:tbl>', fix_tbl, doc_xml, flags=re.S)


# ---------------------------------------------------------------- 分页

def insert_page_breaks(doc_xml, name2id):
    """在完整封面块后、目录（sdt 块）后各插入分页符。"""
    cover_ids = {
        name2id[name]
        for name in ('Title', 'Subtitle', 'Author', 'Date')
        if name in name2id
    }
    if cover_ids:
        toc_start = doc_xml.find('<w:sdt>')
        front = doc_xml[:toc_start] if toc_start >= 0 else doc_xml
        revision = next((
            match for match, _ in styled_paragraphs(front, include_unstyled=True)
            if is_revision_title(match.group(2))
        ), None)
        cover_end = revision.start() if revision else len(front)
        cover = front[:cover_end]
        has_cover = any(
            style in cover_ids for _, style in styled_paragraphs(cover))
        if has_cover and revision:
            doc_xml = (doc_xml[:revision.start()] + PAGE_BREAK
                       + doc_xml[revision.start():])
        elif has_cover:
            paragraphs = list(re.finditer(
                r'<w:p>(?:(?!</w:p>).)*?</w:p>', cover, re.S))
            for paragraph in reversed(paragraphs):
                style = re.search(r'<w:pStyle w:val="([^"]+)"', paragraph.group(0))
                if style and style.group(1) in cover_ids:
                    doc_xml = (doc_xml[:paragraph.end()] + PAGE_BREAK
                               + doc_xml[paragraph.end():])
                    break
    # 目录 sdt 块后分页（文档中第一个 sdt 即目录）
    doc_xml, _ = re.subn(
        r'(</w:sdt>)', lambda m: m.group(1) + PAGE_BREAK, doc_xml, count=1
    )
    return doc_xml


# ---------------------------------------------------------------- 主流程

def fix_docx(path):
    with zipfile.ZipFile(path) as zin:
        entries = {i.filename: zin.read(i.filename) for i in zin.infolist()}
        order = zin.infolist()

    doc = entries['word/document.xml'].decode('utf-8')
    styles = entries['word/styles.xml'].decode('utf-8')
    settings = entries['word/settings.xml'].decode('utf-8')

    ids, name2id = build_name_to_id(styles)
    doc = remap_style_refs(doc, ids, name2id)
    doc = move_cover(doc, name2id)
    doc = move_revision_history(doc, styles, name2id)
    doc = build_toc_sdt(doc, name2id)
    doc = fix_table_widths(doc)
    doc = insert_page_breaks(doc, name2id)
    settings = enable_update_fields(settings)

    entries['word/document.xml'] = doc.encode('utf-8')
    entries['word/settings.xml'] = settings.encode('utf-8')

    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for info in order:
            zout.writestr(info.filename, entries[info.filename])
    shutil.move(tmp, path)
    print('fixed:', path)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('usage: python3 fix_docx.py <file.docx> [...]')
    for p in sys.argv[1:]:
        fix_docx(p)
