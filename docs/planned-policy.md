# 策略已经训练好，怎样再选发送方案？

你已经保存了强化学习策略，想看看少发消息时能否满足自己的误差要求？这条本地流程会固定原 Q 表，只选择发送方式。选择完成后，再用一开始留出的条件复核；不会重新训练，也不会看完测试再换门槛。

目前支持内置一阶对象、单输入和零目标。自定义对象以及 MFAC、ILC 的联合学习与选方案另做。可以直接在本地网页完成，也可以用下面的命令；两条路径使用同一套选择、测试和历史校验。

## 在网页里直接完成

打开本地网页，找到“先选一个发送方案，再换一组条件复核”，把控制方式换成“保存的 Q 策略”。载入完整策略或历史文件；如果刚在上方运行了强化学习，点击“使用本页最新的策略与历史”即可，不用下载再上传。计划运行成功后，这个按钮会接续最新历史，避免退回最初的训练文件。

网页会显示并锁定训练时长、20 ms 步长、内置标量对象和输入上限。若原表单的消息上限或最长间隔超出新时长，会调整并说明改了什么；它们仍可在选择前修改。初态始终使用你声明的固定值，不照搬原独立评测按种子抽取初态的规则。kp、kd 不参与 Q 策略。

填写误差要求、门槛、选择编号和预留测试编号，再点击“只运行选择阶段”。程序不碰预留测试；选择完成后，页面内保留完整记录，下一步按原计划复核。测试结果会显示误差是否达标、实际消息数和失败原因。完整结束与达标不是一回事。

每次成功后，当前策略会接上这一步的已用历史。展开“查看训练、评测和计划用过的编号”核对；重复编号会被拒绝，旧结果仍保留，换新编号可恢复。下载完整报告 ZIP 和最新 `policy-history.json` 再关闭页面；刷新后程序不会自动找到旧历史。复核原选择文件仍是重复执行，不是新增独立测试。

网页策略文件最多 2 MiB，完整选择请求最多 8 MiB，0.2–8 秒、20 ms 步长，总潜在区间最多 20000。超出范围请用本地命令行，不截断策略或删除历史。网页只接受声明格式的 JSON，不执行模型或控制器 Python 代码。

## 先准备策略和方案

已有 `policy-checkpoint.json` 就直接使用。它要和当前仿真代码匹配；单独的旧 `policy.json` Q 表缺少时间和来源信息，不能替代。从头体验时，可以先运行原来的训练案例：

```sh
python -m event_control_lab controller-lab --method rl --out runs/policy-training
```

这一步才会训练，后面的选择与测试都不训练。示例方案对应默认训练的 1.2 秒、20 ms 步长、输入上限 4。自己的策略如果用了别的设置，先把方案的对象、时长、步长、输入上限与训练记录核对；相同步数不能替代相同物理时间。网络、消息上限、固定初值和误差要求由你在选择前声明。

选择和测试各有一组编号；此前看过的其他开发编号填入 `previously_used_seeds`。新编号不能与完整策略中已知的训练、评测、过去选择或测试重叠。工具只能检查你交给它的历史，不能发现未保存的尝试。

## 先选，再按原声明复核

```sh
python -m event_control_lab.planned_study select --spec examples/planned-frozen-policy.json --policy-checkpoint runs/policy-training/policy-checkpoint.json --out runs/policy-choice
python -m event_control_lab.planned_study test runs/policy-choice/selection-bundle.json --out runs/policy-test
```

各目录必须是新目录，已有文件不会覆盖。打开 `report.html`，先看有没有选到方案、每次是否完整结束，再看误差和实际消息数。选择规则沿用原流程：每次完整结束且完整时段 RMSE 达标，然后选平均尝试发送较少的，再比平均误差与声明顺序。没有合格候选就不运行测试；“报告已保存”不等于实验达标。

周期对照也使用同一份 Q 表、初态、随机输入和消息上限。比较的是同一控制策略下的发送方式，不是 Q 策略和线性反馈谁更好；相同上限仍不代表实际消息数相同。失败保留原因与无法计算的指标，不填零，也不会触发改选。

## 初态和原来单独测试有什么区别？

这条计划中，每次都从方案声明的 `initial_position` 开始；种子只改变声明的测量噪声、输入扰动和丢包。原来的 `evaluate-policy` 会按种子生成初态，并运行更多参考。两条路径回答的问题不同，不能把平均数直接拼成同一个比较。

每次运行新建一个控制器，只看已到达的观测和到达时刻。没有探索随机数，没有学习更新，运行前后 Q 表摘要必须相同。原训练失败状态也保留；这些检查不保证策略好用或稳定。

## 下次新计划用哪个文件？

选择和测试目录都输出 `policy-history.json`：它带着完整策略、原评测编号、声明的开发编号，以及每次选择和测试实际用过的编号。另定新的方案和编号后，载入最新历史继续：

```sh
python -m event_control_lab.planned_study select --spec my-next-plan.json --policy-checkpoint runs/policy-test/policy-history.json --out runs/next-choice
```

测试失败也记为已用；如果选择没有合格项，预留测试编号不会冒充已运行。原选择文件可以重复执行，那是复核同一份声明，不是新增独立测试。程序不会自动找到磁盘上其他分支的记录，请保留自己的整条使用历史。

`policy-checkpoint.json` 兼容原独立评测入口，已知开发、选择和测试编号也进入它的已用列表；阶段名称保存在 `policy-history.json` 中，后续计划优先用后者。两者都不改 Q 表。摘要帮助查错，不能认证来源、独立性或自动排除漏报历史。

## 遇到拒绝时

- 文件为空或只有 Q 表：找回完整策略。不会自动改用线性反馈。
- 代码、摘要、时间或输入上限不匹配：保留原文件，回到对应代码版本，或另做有记录的新训练；不要手工补摘要。
- 编号已用：展开报告里的历史，另定方案并换新编号，不删历史来消除提示。
- 没选到方案：先看选择阶段的失败和误差。若修改条件，把已有结果记为开发资料，再开始新计划，不从预留测试里临时挑答案。
- 测试未达标：保留原选择和全部测试。继续调参需要另存开发过程和下一份测试声明。

Python 接口为 `select_with_context(spec, policy_checkpoint=saved)`、`test_with_context(choice)` 和 `export_bundle`。测试从选择记录加载同一份策略，不接收新的 Q 表。`render` 仍只重绘，不再运行，旧记录缺失的环境仍未知。

## English

In the web planned form, choose the saved Q policy mode and load a full checkpoint/history or reuse the policy from the preceding training result. The trained scalar model, physical clock and input limit remain locked; any initial cap/heartbeat adjustment is shown before selection. The CLI remains `planned_study select --spec SPEC --policy-checkpoint CHECKPOINT --out NEW_FOLDER`, followed by `test` on `selection-bundle.json`. Both paths use the same frozen-policy protocol. Each run has a fresh controller, no exploration or learning, and matching table hashes. Both schedules use the same policy and fixed configured initial state, unlike `evaluate-policy`, which samples initial states by seed and runs additional references.

Retain the trained model, physical clock and input limit. Exclude all known training, evaluation, declared development and planned-phase seeds from new selection/test lists. Continue a later plan with the latest `policy-history.json`; the compatible legacy checkpoint also retains the combined used-seed list. Failed attempts remain in history; unrun tests are not consumed. Rerunning an original choice is replication, not new independent testing. All candidates, failures, unknowns and trajectories remain. Declared history and checksums do not certify provenance, independence, stability or general superiority. The developer-observed teaching example is not adoption or hardware evidence.
