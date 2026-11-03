#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import sys

from mcp.server import MCPServer

WORKSPACE = Path(os.environ.get("MD2DOCX_WORKSPACE", "/work")).resolve()
CONVERT = Path("/opt/md2docx/scripts/convert.py")

mcp = MCPServer("markdown-to-docx")


def workspace_path(raw_path):
    if not raw_path or not raw_path.strip():
        raise ValueError("文件路径不能为空")
    path = Path(raw_path)
    resolved = (path if path.is_absolute() else WORKSPACE / path).resolve()
    try:
        resolved.relative_to(WORKSPACE)
    except ValueError as exc:
        raise ValueError(f"路径必须位于挂载目录 {WORKSPACE} 内") from exc
    return resolved


@mcp.tool()
def markdown_to_docx(
    input_path: str,
    output_path: str | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    author: str | None = None,
    date: str | None = None,
    reference_doc: str | None = None,
    toc: bool = True,
    update_toc: bool = True,
) -> dict:
    """把挂载目录中的 Markdown 转成 DOCX；路径使用 /work 内相对路径或绝对路径。"""
    source = workspace_path(input_path)
    if not source.is_file():
        raise ValueError(f"输入文件不存在：{source}")
    output = workspace_path(output_path) if output_path else source.with_suffix(".docx")

    command = [sys.executable, str(CONVERT), str(source), "-o", str(output)]
    for name, value in (
        ("title", title),
        ("subtitle", subtitle),
        ("author", author),
        ("date", date),
    ):
        if value is not None:
            command.append(f"--{name}={value}")
    if reference_doc:
        command.append(f"--reference-doc={workspace_path(reference_doc)}")
    if not toc:
        command.append("--no-toc")
        update_toc = False
    if not update_toc:
        command.append("--no-update-toc")

    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError(
            f"转换失败（退出码 {result.returncode}）：\n{result.stdout}{result.stderr}"
        )
    return {
        "output_path": output.relative_to(WORKSPACE).as_posix(),
        "size_bytes": output.stat().st_size,
        "toc": toc,
        "toc_pages_refreshed": toc and update_toc,
        "message": "DOCX 已生成在宿主机挂载目录的对应位置",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
