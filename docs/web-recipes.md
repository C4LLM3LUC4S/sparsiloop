# 不改代码，从网页做一次控制实验

运行 `python quickstart.py`，打开终端显示的网址。页面可以比较发送策略、运行 MFAC/ILC/强化学习、单独重测保存的策略，也能先选发送方案再复核。各部分的参数分别设置，改上方的延迟不会悄悄改变下面的训练。

## 先从 ILC 开始

点击“试试 MFAC、ILC 和强化学习”。默认是 ILC，可以先运行 3 轮，看看第一轮和后面几轮的位置误差怎样变化。每轮都从相同初态开始，上一轮的误差只用于调整下一轮；学习结果不保证一直改善。

换成 MFAC 后，观察的是单次运行中的估计与控制，不再是跨轮次学习。换成强化学习后，表格先给出新的测试结果，训练过程需要展开查看。测试同时保留未训练策略和固定反馈，方便检查学到的策略是否实际有帮助。不要把不同方法在不同条件下的数值直接排成总榜。

网页中的模型是内置的一阶教学模型，目标位置为 0。训练和 MFAC/ILC 使用完整规则测量，没有延迟、丢包和噪声；强化学习测试可以另外设置消息上限、延迟和丢包，并明确加入固定噪声。初始位置偏差只设置 MFAC/ILC，强化学习的训练和测试初态由各自种子生成。

## 把结果带走

点击“下载完整报告 ZIP”，完整解压，再打开 `report.html`。里面保留设置、所有声明的训练和测试、失败原因、原始轨迹、汇总 CSV 及源码摘要。网页结果没有丢掉训练差或失败的运行；“无法计算”也不是零分。

强化学习结果还可“另存策略”。这个文件包含 Q 表、训练条件、已用种子和来源摘要，不只是旧的原始 Q 表。

## 下次接着测试

选择完整的 `policy-checkpoint.json`，或点击“使用刚才实验保存的策略”。填写 1–5 个新的种子，再点击“只测试，不训练”。这次不会修改 Q 表，时间尺度、模型和输入上限也会核对。

如果不记得哪些编号已经用过，展开“查看已用种子”，就能看到当前文件记录的训练和测试编号，不需要自己翻 JSON。测试成功后，这里也会更新。

测试后，当前页面会记住这次用过的种子。请另存更新后的策略，下一次打开网页时加载新版。重新上传旧文件仍只带有旧历史，工具无法知道你在其他副本或设备上做过哪些测试。编号不同也不能证明统计独立，反复根据测试结果调参更不能算独立测试。

## 没有成功时

想固定已经训练好的策略，只选择发送门槛？在“先选发送方案，再复核”里选择保存的 Q 策略，点击“使用本页最新的策略与历史”，或载入完整策略文件。原时钟和输入上限会锁定，当前计划初态仍由你声明；选择和测试不训练。每步成功后历史继续保留，重复编号会被拒绝。具体操作及这条流程的 0.2–8 秒范围见[冻结策略选择与复核](planned-policy.md)。

- 参数或策略文件不合适：新实验没有开始或没有生成新结果，之前的结果仍显示。先读提示，再修改对应条件；旧下载仍然保留。
- 文件超过 2 MiB、时间尺度不符合网页范围：使用[命令行加载](saved-policy.md)，网页不会自动缩短时域或删掉内容。
- 另一个标签页正在运行：等它完成后再试。同一服务一次只运行一个经典控制任务。
- 浏览器连接中断：确认终端还开着，再刷新。已经下载的 ZIP 不受影响；没有收到的结果需要重新运行，页面不会宣称已经保存。

网页每步为 20 ms，每次模拟 0.2–2 秒，最多 30 轮 ILC、128 个训练种子、5 个测试种子，总仿真区间不超过 20000。接口只接受白名单方法、JSON 设置和完整策略文件，不执行上传的 Python 代码。更多模型、参数或更大实验请用已有 Python/命令行接口。

## English

To select a communication schedule for the frozen scalar Q policy, use the planned form's saved-policy mode. It reuses the preceding training result or loads the full checkpoint/history, keeps the trained clock and input limit, then runs only the declared selection and test phases. See [the complete workflow](planned-policy.md). Training parameters and policies are not selected using these tests.

Open the local web lab with `python quickstart.py`. The controller section configures built-in MFAC, repeated-trial ILC and Q-learning recipes separately from the network comparison above it. Training rows are folded away from test results. Download and fully extract the report ZIP to read it offline with all raw records and failures retained. Load a complete checkpoint in the saved-policy section for evaluation without training; save the updated checkpoint to carry test-seed history into the next session. The web limits are narrower than the CLI: scalar model, 20 ms steps, 0.2–2 s horizons and at most 20000 simulation intervals. It never runs uploaded Python code.
