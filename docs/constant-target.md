# 把位置移到一个固定目标

已有目标位置，不只是想让状态回到零？这条本地任务可以比较同一个位置—速度数学模型在三种发送方式下，离目标还有多少误差、实际用了多少消息。目标在整个实验中保持不变，控制器是固定反馈，不训练策略。

## 先跑一个小任务

需要 Python 3.10+。第一次使用建议下载并完整解压发行 ZIP，先按顶层 `START_HERE.md` 离线安装。在 **ZIP 解压后的顶层目录**运行：

```powershell
.\.venv\Scripts\python.exe -I -m event_control_lab.constant_target run --spec source/examples/constant-target.json --out reports/constant-target
```

完整记录和报告会保存在 `reports/constant-target/`。macOS / Linux 把解释器路径换成 `.venv/bin/python`。**单独的 wheel 不含示例方案文件**；安装 wheel 的使用者还需要下载匹配版本的源码包，或从[完整方案示例](../examples/constant-target.json)另存自己的 JSON。

如果使用克隆仓库或解压后的源码包，在包含 `pyproject.toml` 的源码目录运行：

```powershell
python -m event_control_lab.constant_target run --spec examples/constant-target.json --out runs/constant-target
```

示例从实际位置 0 移向目标 1。打开自己输出目录中的 `report.html`，先核对实际初始位置和目标，再看**目标误差 RMSE**与实际消息账本。这只是一个原创归一化教学任务，不是设备标定或独立用户效果。

把方案另存到自己的文件，再修改 `target`、实际 `config.initial_position`、初始速度、网络或发送设置。不要覆盖已有报告；新实验使用新的 `--out`。`target` 和物理初始位置的教学范围分别是 −5 到 5，初始误差 `initial_position-target` 还必须通过原 Config 的范围与状态界限校验。

## 结果究竟量了什么？

对象为 `p'=v, v'=u+w`，目标是预先声明的常量 `r`。底层沿用误差坐标 `e=p-r`，因此 `e'=v`；恒定目标不需要额外平衡输入。反馈仍只读取已经到达的 `(误差,速度)` 测量：`u=-kp*e-kd*v`。丢包或延迟时保持上一条指令；第一条消息到达前指令是零。

- 完整任务保存在 `target-task.json`。嵌套原比较中的 `state[0]` 和 `position_rmse` 分别表示误差 `e` 和原协议的完整时段误差 RMSE。没有重命名或重算原指标。
- `physical-trajectories.csv` 另列实际位置 `p=e+r`、目标、误差、速度、控制器已收到的值和通信事件。`clipped_command` 是限幅指令；`effective_interval_input` 还包含限幅后加入的输入扰动，末行没有推进区间，留空。
- RMSE 使用既有梯形积分约定。状态按保持输入解析解推进，不等于平方误差积分也是精确连续时间积分。失败运行的完整时段指标保持 `null`。
- 绝对变化发送依据测量差，相对变化发送依据**误差—速度向量**的范数；它不是对绝对物理位置的相对触发。共同消息上限也不等于相同实际通信量。
- `state_limit` 是误差—速度状态的仿真界限，不能解释成实际位置的安全范围。二次代价只是原协议固定权重指标，不是物理能耗。

如果误差没有满足你的任务要求，先确认运行是否完整、是否限幅、预算是否限制请求，再有依据地另设方案复核。保留失败和原结果，不通过删失败、缩短时域或改目标美化一次结果。

## 保存和隔日恢复

保留整个结果目录、原方案、对应发行 ZIP 与准确源码。只看已有结果，直接打开 HTML；只重绘则用这份任务的完整记录：

```powershell
python -m event_control_lab.constant_target render "old results/target-task.json" --out runs/redrawn-target
```

上面是源码目录的命令。使用完整 ZIP 的已安装环境时，在 ZIP 顶层把 `python` 换成 `.\.venv\Scripts\python.exe -I`（macOS / Linux 用 `.venv/bin/python -I`），完整记录路径指向实际保存的位置。不要用 CSV、简化报告或旧策略文件替代完整记录。

这条命令不重新训练、仿真或计算原指标，原执行环境保持不变，只另记重绘环境。记录会核对目标、实际初态、误差设置、原随机输入、源码及结果结构；摘要是自录一致性检查，不能认证来源。旧比较、planned 结果、checkpoint 或 CSV 不能代替 `target-task.json`。

本地导出先保存并读回完整任务。后续报告写出失败或中断时，会打印实际保留的恢复文件和重绘命令。连完整记录本身也未保存或未通过读回时，不承诺恢复。网页临时下载不在这条新任务范围内。

## 这次先支持到哪里？

仅支持内置双积分对象、常值目标和固定反馈。原零目标流程、MFAC、ILC、RL 与旧记录保持各自约定，不能把旧策略直接解释成新目标的策略。标量对象通常需要非零平衡输入，不能仅减一个目标就套用；时变轨迹、私人对象和网页配置另行设计。本任务不认证稳定性、硬件效果、控制方法普遍优势或独立采用。

## English

The local constant-target task supports the built-in double integrator with a fixed known position target and fixed feedback. It reuses the unchanged core in error coordinates `e=p-r`, preserving physical input. The report and CSV separately display physical position and tracking error. Relative events use the error/velocity norm; state limits bound that error state, not physical safety. Commands are clipped before input disturbance. RMSE retains the full-horizon trapezoidal convention and failed results remain null.

After installing from the complete offline ZIP, run from its top level with `.venv/Scripts/python.exe -I -m event_control_lab.constant_target run --spec source/examples/constant-target.json --out reports/constant-target` (use `.venv/bin/python` on macOS/Linux). Source checkouts and extracted sdists instead use `python -m event_control_lab.constant_target ... --spec examples/constant-target.json`. The wheel alone does not include example JSON files.

Keep the complete `target-task.json`, original spec and matching source. `render` validates and redraws the original record without new computation, retaining missing original environments as unknown. Old zero-target comparison/policy/planned files are not this typed task. No scalar reference tracking, learned-policy transfer, varying trajectory, hardware or stability claim is made.
