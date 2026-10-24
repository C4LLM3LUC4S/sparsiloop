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
from .planned_models import FORMAT as MODEL_SELECTION_FORMAT
from .planned_policy import FORMAT as POLICY_SELECTION_FORMAT
from .planned_policy import load_policy_selection
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
    if not isinstance(value, dict) or set(value) not in ({"spec"}, {"spec", "policy_checkpoint"}):
        raise ValueError("请先填写完整方案；这里不接收 Python 代码，也不单独接收测试结果。")
    spec = PlannedSpec.from_dict(value["spec"])
    web_spec(spec)
    policy = value.get("policy_checkpoint")
    if isinstance(policy, dict) and policy.get("format") == "sparsiloop-policy-history-v2":
        raise ValueError("这份完整接续历史请用本地命令 python -m event_control_lab.policy_journal select 继续；网页暂不接收这个新格式，请保留原文件。")
    if "policy_checkpoint" in value and not isinstance(policy, dict):
        raise ValueError("请载入完整策略或策略历史，空值不能代替策略，也不会改用线性反馈。")
    if policy is not None and len(json.dumps(policy, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
        raise ValueError("网页策略文件最多 2 MiB，请用本地命令行保留完整策略与历史。")
    return pack(select_with_context(spec, policy_checkpoint=policy))


def test_from_web(value):
    if not isinstance(value, dict) or set(value) != {"selection"}:
        raise ValueError("复核只接收完整选择记录，不能临时换门槛、参数或测试种子。")
    if isinstance(value["selection"], dict) and value["selection"].get("format") == "sparsiloop-policy-workflow-v1":
        raise ValueError("这份完整接续记录请用本地命令 python -m event_control_lab.policy_journal test 复核；网页暂不接收这个新格式，请保留原文件。")
    saved = as_bundle(value["selection"])
    if saved["context"]["phase"] != "selection":
        raise ValueError("请载入选择记录，不能用测试记录代替。")
    if saved["result"].get("format") == MODEL_SELECTION_FORMAT:
        raise ValueError("这份记录使用本地 Python 模型，请回到原本地程序传入 plant=模型 后复核；网页不执行模型代码。")
    if saved["result"].get("format") == POLICY_SELECTION_FORMAT:
        spec, _ = load_policy_selection(saved["result"])
    else:
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
