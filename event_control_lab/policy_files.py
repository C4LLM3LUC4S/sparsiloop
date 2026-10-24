"""Route saved policy files without changing their numerical or history format."""

from . import planned_policy, policy


HISTORY_RECOVERY = (
    "这是选择/复核流程保存的 policy-history.json。继续原计划，请回到“先选一个发送方案，再换一组条件复核”。"
    "若想单独测试，请在原计划结果中展开“想换一组随机初态再测？”，载入或另存 policy-checkpoint.json；"
    "完整报告 ZIP 中也有这个文件。它保留全部已知的已用编号；阶段名称请继续保存在原 policy-history.json 中。"
    "单独测试会按种子生成初态并增加对照，与原计划的固定初态测试不同。\n"
    "For standalone evaluation, use policy-checkpoint.json from the planned result or its complete ZIP. "
    "Keep policy-history.json for phase names and later plans. Standalone evaluation uses seed-based initial states and additional references."
)


def load_standalone_checkpoint(value):
    if isinstance(value, dict) and value.get("format") == "sparsiloop-policy-history-v2":
        raise ValueError("这份文件保留了跨流程的完整历史，请使用本地接续命令 python -m event_control_lab.policy_journal evaluate --policy 文件 --seeds 新编号 --out 新目录。网页暂不接收这种格式，请保留完整历史，不要删字段改成旧格式。")
    if isinstance(value, dict) and value.get("format") == planned_policy.HISTORY_FORMAT:
        planned_policy.history_for(value)
        raise ValueError(HISTORY_RECOVERY)
    return policy.load_checkpoint(value)
