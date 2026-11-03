#!/usr/bin/env python3
"""Convert Markdown to DOCX with the enterprise-document post-processing pipeline."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REFERENCE_DOC = SCRIPT_DIR.parent / "assets" / "template.docx"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Markdown -> pandoc -> DOCX 后处理 -> LibreOffice 目录页码刷新"
    )
    parser.add_argument("input", type=Path, help="输入 Markdown 文件")
    parser.add_argument("-o", "--output", type=Path, help="输出 DOCX，默认与输入同名")
    parser.add_argument(
        "--reference-doc",
        type=Path,
        default=DEFAULT_REFERENCE_DOC,
        help="pandoc reference-doc，默认使用技能自带模板",
    )
    parser.add_argument(
        "--metadata-file",
        type=Path,
        action="append",
        default=[],
        help="pandoc YAML 元数据文件，可重复；命令行封面参数优先",
    )
    parser.add_argument("--title", help="封面文档名")
    parser.add_argument("--subtitle", help="封面副标题或版本号")
    parser.add_argument("--author", help="封面作者")
    parser.add_argument("--date", help="封面日期")
    parser.add_argument(
        "--resource-path",
        type=Path,
        action="append",
        default=[],
        help="额外图片等资源搜索路径，可重复",
    )
    parser.add_argument("--no-toc", action="store_true", help="不生成目录")
    parser.add_argument(
        "--no-update-toc",
        action="store_true",
        help="不调用 LibreOffice；保留可点击目录骨架，页码留空",
    )
    return parser.parse_args()


def existing_file(path, label):
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label}不存在或不是文件：{path}")
    return path


def main():
    args = parse_args()
    try:
        source = existing_file(args.input, "输入文件")
        reference_doc = existing_file(args.reference_doc, "reference-doc")
        metadata_files = [
            existing_file(path, "元数据文件") for path in args.metadata_file
        ]
    except ValueError as exc:
        raise SystemExit(f"convert: {exc}")

    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise SystemExit("convert: 未找到 pandoc，请先安装并确保它在 PATH 中")

    output = (args.output or source.with_suffix(".docx")).expanduser().resolve()
    if output == source:
        raise SystemExit("convert: 输出路径不能覆盖输入 Markdown")
    if output.exists() and output.is_dir():
        raise SystemExit(f"convert: 输出路径是目录：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    resource_paths = [source.parent, Path.cwd()]
    resource_paths.extend(path.expanduser().resolve() for path in args.resource_path)
    resource_paths = list(dict.fromkeys(str(path) for path in resource_paths))

    handle = tempfile.NamedTemporaryFile(
        prefix=f".{output.stem}-", suffix=".docx", dir=output.parent, delete=False
    )
    temp_output = Path(handle.name)
    handle.close()

    command = [pandoc]
    if os.environ.get("PANDOC_DEFAULTS_FILE"):
        command.append(f"--defaults={os.environ['PANDOC_DEFAULTS_FILE']}")
    command.extend([
        str(source),
        "--from=markdown",
        "--to=docx",
        f"--reference-doc={reference_doc}",
        f"--resource-path={os.pathsep.join(resource_paths)}",
        f"--output={temp_output}",
    ])
    if not args.no_toc:
        command.extend(["--toc", "--toc-depth=3", "--metadata=toc-title=目录"])
    for metadata_file in metadata_files:
        command.append(f"--metadata-file={metadata_file}")
    for key in ("title", "subtitle", "author", "date"):
        value = getattr(args, key)
        if value is not None:
            command.append(f"--metadata={key}={value}")

    try:
        subprocess.run(command, check=True)
        subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "fix_docx.py"), str(temp_output)],
            check=True,
        )
        if not args.no_toc and not args.no_update_toc:
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "update_toc.py"), str(temp_output)]
            )
            if result.returncode == 2:
                print(
                    "convert: 已跳过目录页码刷新；可在 WPS 中 Ctrl+A 后按 F9 更新",
                    file=sys.stderr,
                )
            elif result.returncode != 0:
                raise SystemExit(result.returncode)
        os.replace(temp_output, output)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode or 1)
    finally:
        temp_output.unlink(missing_ok=True)

    print(f"created: {output}")


if __name__ == "__main__":
    main()
