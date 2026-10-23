# 先选发送方案，再换一组条件复核

如果你的问题是“最多发这么多条消息，哪个门槛能满足误差要求？”，先把候选、误差要求和选择规则定下来，再看测试结果。这个流程把选择和测试分开；不用自己在表格里挑完门槛，再不小心把同一组成绩当成测试。

网页和下面的基础命令使用内置一阶或位置—速度模型，以及固定反馈控制器。**这里不训练控制器，只选择发送规则。** 已有自己的模型时，可走[本地模型选择与复核](planned-models.md)，显式传入同一模型并核对参数、单位与来源。MFAC、ILC 和强化学习的联合训练/选择/测试仍单独规划，未接入这里。

## 第一步：把条件写在方案里

想直接在网页操作，运行 `python quickstart.py`，点击“先选发送方案，再复核”。这块表单独立配置，不读取页面上方的比较设置：

1. 填好模型、候选门槛、消息上限、每次位置 RMSE 要求，以及选择、预留测试、此前已用的种子。
2. 点击“只运行选择阶段”，查看所有候选和失败。页面保留完整记录；先下载 ZIP 或另存 `selection.json`，刷新会清除页面内记录。
3. 点击“按原计划复核，不重新选方案”。它只用保存的条件和预留种子，上方后来改的参数不生效。没有合格候选时，不运行测试。
4. 下载这一步的完整报告 ZIP，完整解压再打开 `report.html`。选择阶段的 ZIP 保留全部候选；测试 ZIP 保留全部测试及内嵌的完整选择记录。失败或请求出错时，旧结果及其原条件仍留在页面，不会当成新结果。

留到下次使用，推荐点击“另存选择记录和运行环境”，保存 `selection-bundle.json`。它把原始选择和当时的环境放在一起，下一次复核会检查两者是否对应。原始 `selection.json` 仍可载入，但没有保存的环境会继续标为未知，不会用当前电脑补过去。再次载入同一记录属于重复执行，不是新测试。网页只接受 JSON，不接收 Python 代码。

网页使用两种内置模型、固定反馈、20 ms 步长和 0.2–8 秒总时长；选择加潜在测试最多 20000 个仿真区间，完整请求最多 8 MiB。同一本地服务同时只运行一个学习、策略复用或选择/复核任务；其他标签页会收到稍后再试的提示。大规模或其他时间设置使用下面的命令行流程，原有更完整的参数范围不变。

### 用文件和命令行配置

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
python -m event_control_lab.planned_study test runs/planned-choice/selection-bundle.json --out runs/planned-test
```

这一步只接受完整的选择记录，不接收新的门槛、种子或参数。它核对计算代码、配置、摘要和保存的选择规则，然后只运行此前声明的测试种子。

旧的 `selection.json` 命令也继续可用。它不会自动搜索旁边的环境文件；如果你只载入原始 JSON，原选择时的环境就是“未记录”。想连环境一起保留，请显式选择记录包。

测试保留所选方案和周期对照。两者使用原来声明的共同消息上限、同一网格和同一个种子的外部随机输入；**不会按事件实际发送数重设周期预算**。实际尝试、丢失、到达和在途数都保留。若选中的本来就是周期方案，只运行一次，同时标记两个用途。

报告先说是否完整结束、是否满足原来的误差要求，再列每次实际消息数。即使另一个测试结果更好，也不会自动改选。想继续据此调参时，这组测试就成为开发数据，需要另定后续方案。

## 把报告带走后，也能知道这次做了什么

选择和测试的 HTML 都有“这次模拟的是什么？”：先看是一阶标量对象，还是位置—速度对象，再看初始状态、回到零的目标，以及本阶段使用或预留的随机编号。两种对象是数学示例，没有实物标定；位置—速度对象的 RMSE 要求只考察位置，不是同时约束速度。

展开“核对控制、网络和发送规则”，可以看到固定反馈、指令限幅、到达观测、延迟、丢包、噪声、事件门槛及停止条件。最长尝试间隔同时列请求的秒数和采样网格上的实际步数；预算用完后不能继续保证尝试发送，周期方案也不使用这个间隔。`process_noise` 是每个区间加在限幅指令之后的输入扰动系数，不是连续时间噪声强度；换步长后不能仅因系数相同就认定随机过程相同。

基准配置里的 `seed` 会被本阶段的编号列表替换；绝对候选替换 `threshold`，相对候选替换 `relative_threshold`。相对方案还保留基准绝对底限，周期不使用这两种门槛。一阶对象里的 `kd` 和 `initial_velocity` 保留在完整配置里，但不参与运行。报告会分清这些“保存着的值”和“实际使用的值”，没有选到方案时也不会把预留测试写成已经运行。

完整方案可以直接在 HTML 展开，不必另外打开 JSON。表格中的小数可能缩短显示，原样保存的方案和旁边的 JSON 用于精度核对。若传给报告的配置缺字段，会明确说明记录不完整，不拿默认参数补成一次看似完整的实验。这些说明只帮助核对条件，不认证记录来源或实际效果。

## 保存了什么，出错了怎么办？

### 换一台电脑时，先看环境记录

新命令和网页会保存 `environment.json`，把**选择时、复核时、这次生成报告时**分开记。它只记录 Python 的实现、版本、位数、系统类别、SparsiLoop 版本、浮点表示和 UTC 记录时间；不读取主机名、用户目录、环境变量或完整包列表，也不是一份 `pip freeze`。

`selection-bundle.json` 包含完整原选择和对应环境，下一次复核用它即可。测试目录另有 `test-bundle.json`，保存完整测试和两阶段环境，方便以后只重绘报告。原始 `selection.json`、`test.json`、CSV 和轨迹照常保留，环境不会混进数值记录或改变它们的摘要。

旧记录没有环境时仍标为“未记录”；新测试只记这次测试的环境。没有合格候选时测试不运行，也不会填入测试环境。报告可以只重绘：

```powershell
python -m event_control_lab.planned_study render runs/planned-test/test-bundle.json --out runs/planned-redraw
```

`render` 也接受原始旧 JSON，只生成报告，不运行任何种子。它只把当前环境记作“这次生成报告时”，不会冒充原选择或测试环境。已有目录仍拒绝覆盖。环境信息和摘要由程序自行记录，可以帮助核对是否拿错文件，不能认证记录来源或保证跨平台浮点逐位相同。

如果从 Python 接入，使用带环境的接口；原来的 `select_schedule`、`test_schedule` 数值接口保持不变：

```python
from event_control_lab.planned_study import PlannedSpec
from event_control_lab.planned_context import select_with_context, test_with_context, export_bundle

choice = select_with_context(PlannedSpec())
export_bundle(choice, "runs/api-choice")
tested = test_with_context(choice)
export_bundle(tested, "runs/api-test")
# 以后只重绘：export_bundle(saved_bundle_or_raw_result, "runs/api-redraw")
```

选择目录包含 `selection.json`、`report.html`、`runs.csv`、`trajectories.csv` 和输入文件摘要。`runs.csv` 直接列出策略、门槛、消息上限、时间步长、时长、种子和结果，不需要根据候选编号另翻 JSON 才知道条件。完整 JSON 保留方案、候选、外部随机轨迹、每次运行、失败与选择结果。测试目录的 `test.json` 还带有原选择记录和本次全部测试。

- 提示种子重叠：在运行前分开填写三组编号。不会自动删去重复项，也不会悄悄运行较少种子。
- 摘要或计算版本不一致：回到原文件、原版本复核，不要手动改摘要。仅改报告布局不会使记录失效。
- 环境与结果不对应，或环境摘要不一致：重新选择原来的完整记录包，不把另一份环境文件粘过来，也不手动修摘要。旧的原始 JSON 可以照常读取，缺失环境如实保留。
- 报告目录已存在：换一个新目录，旧结果不覆盖。输入记录只读。
- 命令显示“报告已保存”：表示分析和导出完成，不代表每项仿真或误差要求都通过。终端会同时说明是否选到方案、测试是否满足要求；程序退出码 0 不应直接当成实验验收，自动流程应读取 JSON 的状态。
- 失败或分数无法计算：原始轨迹和原因保留，CSV 的分数为空，报告写“无法计算”，不会填零。
- 规模太大：每类门槛至多 8 个，选择和测试各至多 5 个种子，总潜在仿真区间不超过 40000。减少门槛、种子或时长后，作为另一份方案保存。

重复执行同一个测试文件，是重跑同一份声明，不是增加独立样本。工具无法证明你没有在看到测试结果后重做选择；摘要也不认证来源、预注册、稳定性、硬件效果或普遍优越。公开示例是开发者已看过的流程演示。

已有训练好的策略时，另看[冻结策略选择与复核](planned-policy.md)。它保留训练时钟、Q 表和分阶段已用编号，选择与测试都不再训练；本文默认仍使用固定线性反馈。

## English

Declare candidate thresholds, a common packet cap, an RMSE requirement and disjoint selection/test seed lists. `select` runs only selection seeds, saves every candidate and chooses by a fixed rule: all runs complete and satisfy the RMSE limit, then minimum mean attempts, mean RMSE and declared order. The separate `test` command loads that record and runs only the declared tests and a fixed-cap periodic reference, without reselection. This workflow uses built-in plants and fixed linear feedback, not controller training. It retains failures and raw trajectories. Seed separation and checksums do not certify independent data, preregistration, provenance or stability.

Use `selection-bundle.json` to carry the original choice with its execution environment. Raw JSON remains accepted, with missing execution environments left unknown. `environment.json` separates selection, testing and report rendering; `render` redraws a saved raw result or bundle without simulation. These minimal runtime facts omit hostnames, paths, environment variables and package inventories. They are self-recorded, not authenticated provenance or a guarantee of cross-platform bitwise parity.
