# 换一种测试，也把前面的历史带上

你已经选过发送方案，又想换几组随机初态看看，再做下一个计划？这条流程会保留原文件，把后来的单独评测、开发编号声明、选择和复核依次记下来。全程沿用同一份冻结 Q 表，不需要再训练，也不用手抄一长串已用编号。

目前支持内置一阶模型、单输入和零目标。网页可以直接接着走，较大实验或其他时钟请用本地命令和 Python 接口。

## 在网页里接着做

1. 在“保存的策略，拿出来再测一次”载入完整策略或历史，也可以点击“使用本页最新的策略与历史”。填新编号后，点击“只测试，不训练”。
2. 到下方选择与复核区，选“保存的 Q 策略”，再点击“使用本页最新的策略与历史”。定好候选、选择和预留复核编号，只运行选择阶段。
3. 点击“按原计划复核，不重新选方案”。上方后来改过的条件不会替换原计划。还有待复核计划时，程序会拒绝开始另一项任务。
4. 想再测或做新计划，就载入本页最新历史。点击“保存完整历史，下次接着做”（计划区是“保存完整历史，做下一个任务”），刷新前也保存完整 ZIP。复核用这一阶段的 `selection-workflow.json`，ZIP 同样保留它。后来又重复复核旧方案时，页面不会把接续按钮退回旧历史；本次重复的原记录仍在它的 ZIP 中。若载入另一条分支，页面会说明没有自动合并。兼容 checkpoint 按需展开：它有合并编号，但没有完整阶段顺序。

网页单独测试支持 0.2–2 秒，选择与复核支持 0.2–8 秒，均要求 20 ms 步长。策略请求最多 2 MiB、完整复核请求最多 8 MiB，并保留每次最多 20000 个计算区间的限制。如果这一步已经生成结果，但完整历史太大而无法继续，页面会保留结果、历史和下载，提示转到下方本地命令；不要回退旧历史重复使用编号。

旧网页请求未声明 `keep_history: true` 时继续使用原响应和格式；新页面显式选择完整历史流程。原有固定反馈计划仍走原入口，不改数值或选择规则。

## 先单独测一次，再做新计划

已有完整 `policy-checkpoint.json`，或已经完成原计划的 `policy-history.json`，就可以从第一条命令开始。没有现成策略时，先按[保存策略说明](saved-policy.md)完成一次训练。下面的目录都要是新目录。

```powershell
python -m event_control_lab.policy_journal evaluate --policy runs/last-plan/policy-history.json --seeds 9001,9002 --out runs/extra-tests
python -m event_control_lab.policy_journal select --policy runs/extra-tests/policy-history.json --spec examples/continued-policy-plan.json --out runs/next-choice
python -m event_control_lab.policy_journal test runs/next-choice/policy-workflow.json --out runs/next-test
```

把第一条的文件路径换成自己的。示例编号也要先核对：新测试、选择、预留复核编号不能与已有训练、评测、开发或计划编号重叠。示例方案对应默认策略的 1.2 秒、20 ms 步长、输入上限 4；自己的训练设置不同，就另存一份匹配的方案，不要改策略文件里的摘要。

先用前一份最新历史运行单独评测，再把**这次新输出**的历史交给选择命令。选择只运行第一组编号，复核只运行预留那组，不看测试结果换门槛，也不按事后流量调整周期对照。没有合格候选时，复核会明确保存“没有运行测试”，预留编号不会冒充已经用过。

每一步打开 `report.html`，或打开 `history.html` 看阶段顺序。报告先告诉你怎么继续，再给原始数值与全部失败。报告生成成功，不等于误差要求达标。

## 两个文件，分别什么时候用？

| 想做什么 | 用哪个文件 |
| --- | --- |
| 再单独测一组新编号，或开始新的选择计划 | 最新的 `policy-history.json` |
| 按刚才的选择复核，或只重绘这一步 | 选择/当前阶段的 `policy-workflow.json` |
| 核对原始数值、失败和轨迹 | 同目录的 JSON、CSV，以及旧格式的数值记录 |

新历史使用 v2 格式，原文件原样放在 `origin` 中；后续事件按这条记录的执行顺序附加。开发编号是“在这时补充的声明”，不表示开发实验就在这个时刻发生。原文件没有的阶段或环境仍然未知，不用当前信息补过去。

兼容的 `policy-checkpoint.json` 也会保留全部已知编号，但它没有完整阶段顺序。继续这条流程时，请优先用上表的完整文件。旧入口和旧文件仍可用；程序不会把磁盘上另一条分支自动合并进来。不要回到较早的历史，重复使用后来已经看过的编号。

## 初态和对照变了，结果要分开看

单独评测按种子生成初始位置，每个种子都有三种发送方式和固定反馈对照。计划流程始终使用方案中声明的固定初态，在同一 Q 策略下比较所选方案与周期发送。两条路径使用同一 Q 表，也不能把平均误差直接拼成一次比较。

时间步长、总时长、模型和输入上限保留训练约定。可以在单独评测时用 `--config your-config.json` 声明网络条件；完整条件会保存，变化不能全归因于策略。相同发送上限不代表实际消息数相同，失败的短运行也不是完整任务成本。

## 提示不能继续时

- 还有待复核计划：先用选择阶段的完整记录按原条件复核，再开始单独评测或新计划。这条本地流程按顺序接续，避免新测试被落在另一条分支里。
- 旧历史只到选择阶段：原 v1 文件没有保存完整预留信息。先完成原复核，再载入完整 `test-bundle.json` 作为起点；若没选到合格项，也先保存明确“测试未运行”的复核记录。原文件会原样保留。
- 编号用过了：查看 `history.html`，换新编号，保留旧历史；不要删掉失败来消除提示。
- 来源、Q 表、物理时钟或摘要不匹配：保留原文件，回到生成它的代码版本核对；不要补写摘要，也不会改用另一个策略。
- 输出目录存在：换新目录。程序先在临时目录完成报告，再保存到目标目录，原结果不会覆盖。
- 网页文件或请求超限：保留当前完整下载，使用本页的本地命令接续。不要删掉历史或回到旧文件，也不要改摘要来绕过校验。
- 选择记录没读进来：原结果仍保留，但不会偷偷改用上一个文件。请另选完整的选择记录，或明确点击“使用刚才生成的选择记录”，再复核。

只重新整理保存结果、不再运行：

```powershell
python -m event_control_lab.policy_journal render runs/next-test/policy-workflow.json --out runs/redrawn
```

Python 接口是 `evaluate_saved(saved, seeds, config=None)`、`select_plan(spec, saved)`、`test_plan(choice)`；报告用 `export_workflow(result, destination)`，分别从 `event_control_lab.policy_journal` 和 `policy_journal_report` 导入。读入的原文件不改动，测试不会更新 Q 表。

这些记录只覆盖提供给程序的历史。摘要不认证来源，编号分开不证明统计独立；未提供的尝试、其他分支和漏报的开发过程仍无法自动发现。示例用于核对使用路径，不能当作真实采用、硬件效果或算法普遍优势。

## English

Use `python -m event_control_lab.policy_journal evaluate --policy FILE --seeds NEW_IDS --out NEW_FOLDER`, then `select --policy NEW_HISTORY --spec PLAN --out NEW_FOLDER`, followed by `test POLICY_WORKFLOW --out NEW_FOLDER`. Continue new tasks with the latest `policy-history.json`; repeat or redraw a saved step with its `policy-workflow.json`. The v2 history preserves the original supplied file and appends subsequent declarations, selections, tests and standalone evaluations in order. Declarations are not simulated experiments. Pending plans must be tested before starting another task; unrun tests do not consume their seed numbers. A legacy history ending at selection needs its complete test record to resolve whether tests ran.

No retraining, exploration or test-based reselection occurs. Standalone tests use seed-based initial states and additional references; planned tests retain the declared fixed initial state and a common message cap. Keep these protocols separate. Original numerical exports, failures and unknown values remain; execution and report-rendering environments are distinct. Existing v1 formats and their source identities are unchanged. In the web interface, use the latest complete policy/history, evaluate with fresh IDs, select a schedule, then test the original saved choice. Save the complete ZIP and latest history before refreshing. The web adapter retains its 20 ms clock, bounded horizons/workload and 2 MiB policy / 8 MiB complete-request limits; completed results and downloads remain available if continuation becomes too large. Flag-less HTTP clients keep their original contracts. Checksums and declared histories do not authenticate provenance, merge unprovided branches, or establish independent testing or stability.
