"""Bounded local-web transport for the existing planned selection protocol."""

import base64
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile

from .engine import Config
from .planned_study import PlannedSpec, load_selection
from .planned_context import as_bundle, export_bundle, selection_bundle, select_with_context, test_with_context


MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_INTERVALS = 20000


def default_specification():
    return asdict(PlannedSpec(config=Config(duration=4, budget=40), rmse_limit=0.4))


def web_spec(spec):
    if spec.config.dt != 0.02 or not 0.2 <= spec.config.duration <= 8:
        raise ValueError("网页先支持每步 20 ms、总时长 0.2–8 秒；其他时间设置请用命令行。")
    count = 1 + len(spec.absolute_thresholds) + len(spec.relative_thresholds)
    if (count * len(spec.selection_seeds) + 2 * len(spec.test_seeds)) * spec.config.steps > MAX_INTERVALS:
        raise ValueError("这组选择和测试超过网页的 20000 个仿真区间限制，请减少候选、种子或时长。")


def pack(value):
    saved = as_bundle(value)
    record = saved["result"]
    testing = saved["context"]["phase"] == "test"
    selection = selection_bundle(saved)
    # Leave room for the envelope when this complete record is sent back for testing.
    if len(json.dumps({"selection": selection}, ensure_ascii=False).encode()) > MAX_REQUEST_BYTES:
        raise ValueError("完整选择记录超过网页的 8 MiB 限制，请用命令行保存和复核，或减少实验规模。")
    with tempfile.TemporaryDirectory(prefix="sparsiloop-planned-web-") as temporary:
        output = Path(temporary) / "report"
        manifest = export_bundle(saved, output)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output.iterdir()):
                archive.writestr(path.name, path.read_bytes())
    content = buffer.getvalue()
    return {"mode": "test" if testing else "selection", "record": record,
            "context": saved["context"], "selection_context": selection["context"],
            "report_runtime": manifest["report_rendering"],
            "archive_base64": base64.b64encode(content).decode("ascii"),
            "archive_sha256": hashlib.sha256(content).hexdigest()}


def select_from_web(value):
    if not isinstance(value, dict) or set(value) != {"spec"}:
        raise ValueError("请先填写完整方案；这里不接收 Python 代码，也不单独接收测试结果。")
    spec = PlannedSpec.from_dict(value["spec"])
    web_spec(spec)
    return pack(select_with_context(spec))


def test_from_web(value):
    if not isinstance(value, dict) or set(value) != {"selection"}:
        raise ValueError("复核只接收完整选择记录，不能临时换门槛、参数或测试种子。")
    saved = as_bundle(value["selection"])
    if saved["context"]["phase"] != "selection":
        raise ValueError("请载入选择记录，不能用测试记录代替。")
    spec = load_selection(saved["result"])
    web_spec(spec)
    return pack(test_with_context(saved))


def error_message(detail):
    if any("\u4e00" <= char <= "\u9fff" for char in detail):
        return detail
    messages = (
        ("request must contain", "这次请求为空或超过 8 MiB，请缩小记录，或用命令行复核。"),
        ("budget and delay_steps", "发送上限或延迟步数超过了仿真范围，请调小后再试。"),
        ("heartbeat must", "最长发送间隔要在一个步长和总时长之间，请核对一下。"),
        ("duration must", "总时长需要是 20 ms 的整数倍，比如 1.2 秒或 4 秒。"),
        ("gains", "固定反馈增益要在 0 到 20 之间。"),
        ("initial state", "初始位置和速度要在 −5 到 5 之间，也不能超过停止上限。"),
    )
    for text, message in messages:
        if text in detail:
            return message
    return "这份方案或选择记录暂时不能运行。请核对数字、文件格式和版本；原始错误可以展开查看。"
