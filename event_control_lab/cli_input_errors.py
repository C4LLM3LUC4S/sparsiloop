"""Recovery wording for local JSON input errors, outside numerical identity."""

import json
from pathlib import Path


NESTED_JSON_RECOVERY = (
    "这份 JSON 的嵌套层级太深，程序没能读完。先保留原文件，确认它是当前命令需要的完整配置、策略或结果，"
    "再从原生成程序重新导出后重试。不要手工压平内容、删减历史、只截取 Q 表，或提高递归限制。\n"
    "This JSON is nested too deeply to read. Keep the original and re-export the complete configuration, policy "
    "or result needed by this command from its generating program. Do not flatten the data, drop history, "
    "extract only the Q table, or raise the recursion limit."
)


def read_cli_input(path, reader):
    """Keep the original reader's format and limits; diagnose only its input stage."""
    try:
        return reader(path)
    except RecursionError as exc:
        raise ValueError(f"输入文件 / Input file: {Path(path)}\n{NESTED_JSON_RECOVERY}\n"
                         f"原始错误 / Original error: RecursionError: {exc}") from exc


def read_cli_json(path, *, encoding="utf-8-sig"):
    return read_cli_input(path, lambda value: json.loads(Path(value).read_text(encoding=encoding)))


def recursion_failure(exc):
    """A later recursion failure does not establish an unreadable JSON input."""
    return ("本次操作没能完成，尚未确认新的完整报告。请保留原输入和已有文件，并记录命令与错误以便排查。\n"
            "The operation could not finish; a new complete report has not been confirmed. "
            "Keep the original inputs and existing files, and retain the command and error for diagnosis.\n"
            f"原始错误 / Original error: RecursionError: {exc}")
