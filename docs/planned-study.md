# 先选发送方案，再换一组条件复核

如果你的问题是“最多发这么多条消息，哪个门槛能满足误差要求？”，先把候选、误差要求和选择规则定下来，再看测试结果。这个流程把选择和测试分成两个命令；不用自己在表格里挑完门槛，再不小心把同一组成绩当成测试。

它使用内置一阶或位置—速度模型，以及固定反馈控制器。**这里不训练控制器，只选择发送规则。** MFAC、ILC、强化学习和自定义模型暂不接入这个流程；原有接口仍单独使用。

## 第一步：把条件写在方案里

复制 `examples/planned-study.json`，按你的任务修改：

- `config`：模型、时间步长、总时长、共同消息上限、延迟、丢包、噪声和固定反馈增益。
- `absolute_thresholds` / `relative_thresholds`：你愿意比较的门槛。周期发送也始终是一个候选；某一类门槛可以留空。
- `rmse_limit`：每个种子的完整时段位置 RMSE 都必须满足的上限。它概括整个时段的位置偏差，**不是每个时刻的最大误差限制**。
- `selection_seeds`：用来选择门槛的条件编号。
- `test_seeds`：先留着的条件编号；第一步只记录，不运行。
- `previously_used_seeds`：此前训练或调参已经看过的编号，可留空。工具只知道你声明的记录，不能自动找出漏报的历史。

三组种子要分别声明、互不重叠；同一组也不能重复。编号不同本身不证明统计独立。初始位置和其他条件保持方案中的设置，种子改变的是测量、扰动和丢包的随机输入。

## 第二步：只用选择数据选一个方案

```powershell
python -m event_control_lab.planned_study select --spec examples/planned-study.json --out runs/planned-choice
```

打开新目录里的 `report.html`。所有候选都保留，程序按预先固定的规则选择：

1. 每个选择种子都要完整运行，而且每次的 RMSE 都不超过上限。任何提前失败或无法计算，都不能成为合格候选。
2. 在合格候选里，先选平均尝试发送最少的。丢包也占用尝试次数。
3. 尝试数相同时，比较平均 RMSE；仍相同时，按声明顺序选择：周期、绝对门槛列表、相对门槛列表。

这只是当前有限候选和规则内的选择，不是搜索到全局最优。如果没有候选满足要求，报告会说明没有选到，测试阶段也不会运行。可以保留这个结论；如果决定修改条件，请另存方案，并记录自己已经看过的数据。

## 第三步：载入保存的选择，再复核

```powershell
python -m event_control_lab.planned_study test runs/planned-choice/selection.json --out runs/planned-test
```

这一步只接受完整的选择记录，不接收新的门槛、种子或参数。它核对计算代码、配置、摘要和保存的选择规则，然后只运行此前声明的测试种子。

测试保留所选方案和周期对照。两者使用原来声明的共同消息上限、同一网格和同一个种子的外部随机输入；**不会按事件实际发送数重设周期预算**。实际尝试、丢失、到达和在途数都保留。若选中的本来就是周期方案，只运行一次，同时标记两个用途。

报告先说是否完整结束、是否满足原来的误差要求，再列每次实际消息数。即使另一个测试结果更好，也不会自动改选。想继续据此调参时，这组测试就成为开发数据，需要另定后续方案。

## 保存了什么，出错了怎么办？

选择目录包含 `selection.json`、`report.html`、`runs.csv`、`trajectories.csv` 和输入文件摘要。`runs.csv` 直接列出策略、门槛、消息上限、时间步长、时长、种子和结果，不需要根据候选编号另翻 JSON 才知道条件。完整 JSON 保留方案、候选、外部随机轨迹、每次运行、失败与选择结果。测试目录的 `test.json` 还带有原选择记录和本次全部测试。

- 提示种子重叠：在运行前分开填写三组编号。不会自动删去重复项，也不会悄悄运行较少种子。
- 摘要或计算版本不一致：回到原文件、原版本复核，不要手动改摘要。仅改报告布局不会使记录失效。
- 报告目录已存在：换一个新目录，旧结果不覆盖。输入记录只读。
- 命令显示“报告已保存”：表示分析和导出完成，不代表每项仿真或误差要求都通过。终端会同时说明是否选到方案、测试是否满足要求；程序退出码 0 不应直接当成实验验收，自动流程应读取 JSON 的状态。
- 失败或分数无法计算：原始轨迹和原因保留，CSV 的分数为空，报告写“无法计算”，不会填零。
- 规模太大：每类门槛至多 8 个，选择和测试各至多 5 个种子，总潜在仿真区间不超过 40000。减少门槛、种子或时长后，作为另一份方案保存。

重复执行同一个测试文件，是重跑同一份声明，不是增加独立样本。工具无法证明你没有在看到测试结果后重做选择；摘要也不认证来源、预注册、稳定性、硬件效果或普遍优越。公开示例是开发者已看过的流程演示。

## English

Declare candidate thresholds, a common packet cap, an RMSE requirement and disjoint selection/test seed lists. `select` runs only selection seeds, saves every candidate and chooses by a fixed rule: all runs complete and satisfy the RMSE limit, then minimum mean attempts, mean RMSE and declared order. The separate `test` command loads that record and runs only the declared tests and a fixed-cap periodic reference, without reselection. This workflow uses built-in plants and fixed linear feedback, not controller training. It retains failures and raw trajectories. Seed separation and checksums do not certify independent data, preregistration, provenance or stability.
