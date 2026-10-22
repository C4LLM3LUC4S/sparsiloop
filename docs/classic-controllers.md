# MFAC、ILC 与强化学习控制 / Classical controller recipes

想看看控制器是怎么逐步学会把对象带回目标位置的，可以从这三个案例开始。MFAC 边运行边估计，ILC 用上一轮的误差改进下一轮，强化学习先训练再测试。它们采用不同流程，适合分别观察学习过程，不适合按一张总榜比较优劣。

These independently implemented teaching recipes show online adaptation, learning across repeated trials, and policy training followed by held-out evaluation. They also work from an installed wheel. The fixed-feedback and optional simple-pid paths remain available.

```powershell
python -m event_control_lab controller-lab --out runs/controllers
```

打开输出目录中的 `report.html`，先看“从哪里开始看”。想追溯每一步时，再展开训练记录，或查看 `controllers.json`；其中保存了参数、种子、轨迹、随机输入和学习更新。`summary.csv` 方便汇总分析，`trajectories.csv` 保留全部轨迹，`policy.json` 保存训练后的策略。每次请使用新目录，避免覆盖前一次实验。

只运行一种：`--method mfac`、`--method ilc`、`--method rl`。默认 `all`。这三个案例目前均以一阶教学对象为起点；网页的原固定反馈比较仍支持两个对象。

| 方法 | 学什么 | 当前接入条件 | 先看什么 |
| --- | --- | --- | --- |
| CFDL-MFAC | 单次运行中估计输入增量与输出增量的局部关系 | 每步收到样本、无延迟/丢包 | phi 估计、重置原因、实际限幅输入 |
| 移位 P 型 ILC | 用上一轮收到的误差改下一轮前馈 | 同初态、固定时域、完整规则采样、无噪声 | 所有轮次与学习是否实际执行 |
| RLC / tabular Q-learning | 通过奖励更新离散动作价值 | 训练时完整规则采样；冻结后按三种网络策略评测 | 未参与训练的种子、冻结指纹、失败与未训练/固定反馈参考 |

三者的训练/运行条件不同，不据此横向排名。默认参数为公开声明的教学选择，未以评测种子选择最佳值。RLC 在本例中可能明显差于固定反馈；不隐藏这些结果。

## CFDL-MFAC

零参考、单输入单输出。每步用已收到的 `y(k)` 及自己此前施加的**限幅后**输入：

```text
du = u(k-1) - u(k-2)
dy = y(k) - y(k-1)
phi_hat = phi_previous + eta*du*(dy - phi_previous*du)/(mu + du**2)
u(k) = clip(u(k-1) - rho*phi_hat*y(k)/(penalty + phi_hat**2))
```

首次没有输出差分，保持声明的 `phi0`，输入历史初始化为零。`phi0` 的符号和大小是先验参数，不从仿真真值反推出。输入增量太小、估计太小/大或符号变化时重置并记录原因。上界与限幅属于本教学实现的显式选择；没有沿用论文的理论保证。不规则样本或迟到包会触发明确错误，不把它们当相邻离散样本。

Formula background: Zhao et al., [author-accepted manuscript](https://kar.kent.ac.uk/105347/1/accepted%20version.pdf), equations (6)–(9), DOI [10.1016/j.conengprac.2024.105912](https://doi.org/10.1016/j.conengprac.2024.105912). The SISO teaching update follows the compact-form idea; it does **not** implement that paper's tensor-product method or reproduce its experiments. Paper/code licensing remain separate; the PDF is not redistributed.

## ILC：学习发生在两轮之间

每轮控制为 `u_j(k)=clip(v_j(k)-kp*y_j(k))`。同一对象、初态与时域重新运行，整轮结束后才计算：

```text
v_(j+1)(k) = clip(v_j(k) - learning_gain*y_j(k+1))
```

这是零参考、Q 滤波器为恒等的移位 P 型前馈学习。学习只使用控制器实际收到的样本，不读取导出中的隐藏真值。核心链路在 `[0,T)` 发送，因此没有送达 `y(T)`；最后一个前馈槽保持零，不能声称它已学习。失败轮保留，缺失样本不补零，也不进行该轮更新。最后一轮只验证已使用的信号，不宣称下一轮改进。

Background: Bristow, Tharayil and Alleyne, [A survey of iterative learning control](https://doi.org/10.1109/MCS.2006.1636313), 2006; [author institution record](https://experts.illinois.edu/en/publications/survey-of-iterative-learning-control-a-learning-based-method-for-/). The hosted survey PDF timed out during this check; this is an explicit, independently checked teaching choice, not a reproduction of a specified survey example. No convergence claim is inherited.

## RLC：训练与冻结评测分开

默认 128 个训练种子，各运行 60 个输入区间。训练种子与评测种子必须唯一且互不重叠。每轮初始位置来自声明的独立随机流 `Random(seed XOR 0x494E4954).uniform(-1.5,1.5)`，动作探索用另一个固定流。最终训练轮后的 Q 表直接冻结；没有选择“最好种子”或以评测结果调参。

Q 状态为 `(到达时刻的步号, 已收到位置的离散桶)`；动作是声明输入上限的 `[-1,-0.5,-0.25,0,0.25,0.5,1]` 倍。桶范围、越界截断、学习率、折扣与探索率均导出；同值时优先小绝对输入，再选较小动作索引。

```text
reward = -dt*(next_received_position**2 + 0.01*previous_action**2)
Q(s,a) += alpha*(reward + gamma*max Q(next_s,.) - Q(s,a))
```

最后收到的网格样本被声明为**学习窗口终点**，它的后继价值为零。没有 `y(T)`，不更新最后未观测的转移，也不把它的奖励设为零。仿真报告仍保留完整 `[0,T]` 状态指标；训练奖励不冒充这项指标。位置离散化及迟到观测不保证 Markov 性；有限训练不满足收敛定理的全部条件。

冻结后，在固定的 3 个未训练种子上，各运行周期、绝对、相对发送策略，同时保留未训练零表、固定线性反馈参考。配置、实际消息数及失败逐项保存。默认评测增加延迟/丢包/噪声，属于显式分布变化；不是对这些条件专门训练过的策略。

Algorithm source: Watkins and Dayan, [Q-learning](https://www.gatsby.ucl.ac.uk/~dayan/papers/cjch.pdf), 1992, DOI 10.1007/BF00992698. A tabular implementation is a baseline; it is not a claim to reproduce continuous-control optimality.

重新使用冻结策略：

```python
import json
from pathlib import Path
from event_control_lab import compare
from event_control_lab.controller_lab import teaching_config
from event_control_lab.controllers import QController, QTable

table = QTable.from_snapshot(json.loads(Path("runs/controllers/policy.json").read_text()))
result = compare(teaching_config(), lambda config: QController(config, table))
```

载入会核对维度、范围、重复状态和非有限数；推理不更新 Q 表。改变训练时域或输入上限需重新训练。`--spec your-spec.json` 可声明配置、MFAC 参数、ILC 轮数/增益、Q 参数及种子；实际解析后的完整参数始终导出。

The report is an engineering/teaching artifact. It does not establish stability, hardware safety, general superiority, independent human adoption, or time saved.
