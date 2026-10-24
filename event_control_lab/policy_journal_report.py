"""Reports and atomic publication for the local chronological policy workflow."""

import html
import json
from pathlib import Path
import tempfile

from . import planned_context, policy
from .planned_report import page, table, write_json
from .policy_journal import load_workflow, origin_history


def history_page(value):
    history = value["history_after"]
    original = origin_history(history["origin"])
    names = {"declared_development": "补充开发编号（声明）", "selection": "选择发送方案",
             "test": "按原计划复核", "evaluation": "单独评测"}
    rows = []
    for index, event in enumerate(history["events"], 1):
        rule = ("按种子生成初态；三种发送方式及固定反馈对照" if event["phase"] == "evaluation" else
                "固定声明初态；同一策略和发送上限" if event["phase"] != "declared_development" else
                "只记录使用者提供的编号，这一步没有仿真")
        stamp = event["runtime"]["captured_at_utc"] if event["runtime"] else "未记录原开发运行时间"
        rows.append([index, names[event["phase"]], ", ".join(map(str, event["seeds"])), rule, stamp])
    origin = {"training_seeds": original["checkpoint"]["training_seeds"],
              "earlier_evaluation_seeds": original["earlier_evaluation_seeds"],
              "declared_development_seeds": original["declared_development_seeds"],
              "planned_history": original["planned_history"]}
    body = '<section><h2>下次从哪个文件接着做？</h2><p>做新任务，用最新的 <a href="policy-history.json" download>policy-history.json</a>；它保留起点文件和后续每个阶段。复核或重绘当前这一步，用 <a href="policy-workflow.json" download>policy-workflow.json</a>。</p>'
    body += '<p>请沿同一条记录接着走。程序不会自动找到其他目录或合并另一分支；若按测试结果继续调参，要记录探索并另定新条件。</p><p>原 Q 表没有更新，已知编号全部保留。摘要只核对文件是否对应，不认证来源或独立性。</p></section>'
    body += '<section><h2>起点文件里原来记了什么？</h2><p>原文件原样保存在新历史的 origin 字段中。下面只整理它已有的编号；无法从当前电脑补出更早的时间或缺失阶段。</p><details><summary>查看起点中的训练、评测和计划编号</summary><pre>'
    body += html.escape(json.dumps(origin, ensure_ascii=False, indent=2)) + '</pre></details></section>'
    body += '<section><h2>载入起点后，依次做过哪些事？</h2>'
    body += table(["顺序", "阶段", "编号", "怎么运行", "记录的 UTC 时间"], rows)
    body += '<p>“补充开发编号”是使用者在这时提供的声明，不代表开发实验发生在这个时刻。单独评测会换初态并增加对照；计划复核保持原声明初态，两者不能拼成同一次比较。</p></section>'
    body += '<section><h2>数值与失败去哪里核对？</h2><p><a href="report.html">返回当前阶段的完整报告</a>。原始数值、所有运行、失败与无法计算的指标仍随报告保存。旧入口的数值记录只有兼容的已用编号视图；继续完整阶段历史时，请使用本页给出的两个完整文件。</p><details><summary>English</summary><p>The supplied v1 origin remains intact. Subsequent declarations, selections, planned tests and standalone evaluations are appended in order. Declarations are not simulated experiments. Standalone evaluations use seed-based initial states and additional references; planned tests retain the declared fixed initial state. Keep the latest history and full workflow record. This does not merge unprovided branches or certify provenance or independence.</p></details></section>'
    return page("接着上次的策略往下做", body)


def export_workflow(value, destination, input_hash=None):
    saved = load_workflow(value)
    target = Path(destination)
    if target.exists():
        raise ValueError("输出目录已存在，请换新目录，旧结果不会覆盖。")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sparsiloop-journal-", dir=target.parent) as temporary:
        folder = Path(temporary) / "report"
        if saved["phase"] == "evaluation":
            policy.export_evaluation(saved["data"], folder)
        else:
            planned_context.export_bundle(saved["data"], folder, input_hash)
        compatible = json.loads((folder / "policy-checkpoint.json").read_text(encoding="utf-8"))
        if compatible != saved["history_after"]["checkpoint"]:
            raise ValueError("导出的完整策略与接续历史不一致，没有保存新报告。")
        old_history = folder / "policy-history.json"
        if old_history.exists():
            old_history.rename(folder / "numeric-policy-history-v1.json")
        write_json(folder / "policy-history.json", saved["history_after"])
        write_json(folder / "policy-workflow.json", saved)
        write_json(folder / "journal-environment.json", {
            "phase": saved["phase"], "execution": saved["execution_runtime"],
            "report_rendering": planned_context.runtime_info(), "input_sha256": input_hash,
            "scope": "Self-recorded execution and rendering facts; not authenticated provenance"})
        (folder / "history.html").write_text(history_page(saved), encoding="utf-8")
        report = folder / "report.html"
        text = report.read_text(encoding="utf-8")
        notice = ('<section id="policy-continuation"><h2>这一步已接在原历史之后</h2>'
                  '<p>查看<a href="history.html">完整阶段顺序和下一步操作</a>。新任务请载入最新 '
                  '<a href="policy-history.json" download>policy-history.json</a>；复核或重绘当前这一步，'
                  '请保存 <a href="policy-workflow.json" download>policy-workflow.json</a>。'
                  '下方的原数值记录仍保留，单独使用它们不能代替完整阶段历史。</p></section>')
        end = text.find("</h1>")
        if end < 0:
            raise ValueError("原报告缺少标题，没有保存新报告。")
        report.write_text(text[:end+5]+notice+text[end+5:], encoding="utf-8")
        if target.exists():
            raise ValueError("输出目录已存在，请换新目录，旧结果不会覆盖。")
        folder.rename(target)
