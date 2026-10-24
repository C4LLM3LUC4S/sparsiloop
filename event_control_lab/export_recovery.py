"""Retain a complete local result when its report cannot finish writing."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile


MODULES = {"planned": "event_control_lab.planned_study", "history": "event_control_lab.policy_journal"}


def quote_path(value):
    text = str(value)
    return "'" + text.replace("'", "''") + "'" if os.name == "nt" else shlex.quote(text)


class ExportRecoveryError(OSError):
    def __init__(self, record, destination, kind, cause):
        self.record_path = record
        self.original_error = getattr(cause, "original_error", cause)
        self.interrupted = isinstance(cause, KeyboardInterrupt) or getattr(cause, "interrupted", False)
        self.redraw_output = destination.parent / ("recovered-report-" + record.stem.rsplit("-", 1)[-1])
        self.module = MODULES[kind]
        executable = quote_path(sys.executable)
        executable = "& " + executable if os.name == "nt" else executable
        flags = " -I" if sys.flags.isolated else ""
        self.command = (f"{executable}{flags} -m {self.module} render {quote_path(record)} "
                        f"--out {quote_path(self.redraw_output)}")
        super().__init__(
            f"报告没能完整保存。完整计算记录已保留：{record}\n"
            "保存位置恢复可用后，可以用下面的命令重新生成报告，不会重新运行实验：\n"
            f"{self.command}\nFull record retained; redraw without new runs.\n"
            f"原始错误 / Original error: {type(self.original_error).__name__}: {self.original_error}"
        )


def discard(record):
    try:
        record.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@contextmanager
def recovery_record(value, destination, kind, *, enabled=True):
    if type(enabled) is not bool or kind not in MODULES:
        raise ValueError("invalid export recovery option")
    if not enabled:
        yield None
        return
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise FileExistsError("输出目录已存在，请换新目录，旧结果不会覆盖。")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix="sparsiloop-recovery-", suffix=".json", dir=target.parent)
    record = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        discard(record)
        raise
    try:
        yield record
    except (OSError, KeyboardInterrupt) as exc:
        raise ExportRecoveryError(record, target, kind, exc) from exc
    except BaseException:
        discard(record)
        raise
    else:
        if not discard(record):
            try:
                print(f"报告已保存；备用记录也保留在 {record}。 / Report saved; recovery copy retained.",
                      file=sys.stderr)
            except (OSError, UnicodeError):
                pass
