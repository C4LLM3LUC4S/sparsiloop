# 步长会不会改变结论？ / Check the sampling grid

精确保持输入状态更新不等于事件触发时刻或梯形积分不受步长影响。此工具在三个固定采样网格上重跑同一个无噪声案例，单独列出触发差异与位置 RMSE 的积分偏差。它不自动认证收敛或选出更好的控制策略。

```powershell
python -m event_control_lab grid-check --spec examples/grid-check.json --out runs/grid-check
```

输出目录必须不存在。失败或不合法的网格不会被悄悄调整。

## 固定了什么

`config.dt * config.delay_steps` 是固定物理延迟。示例为 0.04 秒，步长 0.02、0.01、0.005 秒分别使用 2、4、8 步延迟。对象、时域、初始状态、反馈增益、输入限幅、发送上限及 heartbeat 均固定。

工具要求：

- 2–4 个从粗到细的嵌套网格，每个较粗步长是最细步长的整数倍。
- 时域、物理延迟和 heartbeat 能对齐所有网格；使用与仿真 heartbeat 相同的 4 ULP 整点约定。
- 周期发送上限整除每个网格的总步数，以固定周期发送机会的物理时刻。零预算允许。
- 丢包、测量噪声和输入扰动均为零。随机案例明确拒绝；同一离散种子不能证明不同步长下使用了同一个连续随机过程。

以上约束不代表一般仿真只能这样设置，而是避免本次步长检查同时改变多个实验条件。若被拒绝，请选择共同的物理时间点，或先使用示例的确定性配置。

## 怎样读导出

- `grid.json`：每个步长的完整配置、源码指纹、消息账本、原始轨迹、逐格结果和汇总。
- `summary.csv`：每个步长与策略的程序 RMSE、保持输入解析积分参考值，以及两者之差。
- `changes.csv`：各较粗网格相对最细网格的共同物理时刻状态差、完整时域 RMSE 差与实际尝试发送数差。

`held_input_reference_rmse` 使用 50 位 Decimal 对每个导出区间的起始状态与保持输入做解析积分。一阶对象使用指数函数的平方积分，位置—速度对象使用二次位置轨迹的平方积分。它独立于核心状态推进函数，但仍依赖导出数据，只复核位置积分，不认证控制器质量或二次代价的全部组成。

先查看周期策略在共同时间点的状态差。在本工具约束下，其调度相同，差应接近浮点舍入水平。再看事件策略：检查机会随网格变密，实际发送时刻、次数和轨迹都可能改变，应据实记录。最细网格只是对照，不是真值；一次三网格检查也不是连续时间稳定性证明。

提前失败的原始轨迹和状态保留，完整时域参考值及相关差值为 `null`，CSV 中留空，不能当成零分或成功收敛。发送次数仍如实保留。

## 固定教学案例的实际观察

2026-10-22，在 Windows/Python 3.12 下运行本例及仅把对象改为 `double_integrator` 的副本，两个对象 × 三网格 × 三策略共 18 次运行均完整结束。物理延迟固定为 40 ms，周期发送时刻保持相同。

周期轨迹在共同时间点的最大状态差分别约为 `8.0e-15` 和 `2.0e-15`。一阶对象的周期位置 RMSE 梯形积分偏差依次约为 `3.14e-6`、`7.85e-7`、`1.96e-7`。这些是该配置的数值结果，不是一般误差上界。

事件策略确有网格依赖：位置—速度对象的绝对变化策略在 20 ms 网格比 5 ms 网格少尝试发送 4 条消息，共同时间点状态最大差约为 `0.0102`。一阶绝对变化策略的共同时间点状态差也没有随网格单调减少，不能把“步长减半”自动写成“结果更优”。应一起查看轨迹、实际通信量和完整时域指标。

这些全部是软件开发者执行的确定性教学案例，不是真实设备、独立用户或算法普遍优越性的证据。为复核，分别运行示例原文件及把 `config.plant` 改为 `double_integrator` 的副本，输出到两个新目录；保留其他字段。

## English

Run the command above to compare deterministic nested grids at fixed physical delay, horizon, gains, heartbeat and periodic opportunity times. Nonzero noise/loss, non-nested grids and misaligned schedules are rejected instead of silently changed.

Read `summary.csv` for the difference between trapezoidal position RMSE and a separate held-input integral. Read `changes.csv` for state and traffic changes relative to the finest requested grid. The finest grid is a comparison reference, not ground truth. Event schedules can change as sampling becomes finer. Incomplete runs keep their raw data; full-horizon values remain unavailable. This is an engineering diagnostic, not a stability or superiority certificate.
