# 保存的策略，怎么拿出来再测一次？

如果只想换一组随机条件看看表现，不需要每次都重新训练。这个入口会读取保存的策略和训练条件，在新的种子下运行，并保留固定反馈控制作为对照。

## 先保存策略，再单独测试

在项目目录中运行，也可以使用已安装的包：

```powershell
python -m event_control_lab controller-lab --method rl --out runs/training
python -m event_control_lab evaluate-policy runs/training/policy-checkpoint.json --seeds 2001,2002,2003 --out runs/new-test
```

打开 `runs/new-test/report.html`。这次只有测试，没有新的训练过程。每个种子都运行三种发送策略，并与相同条件下的固定反馈结果对照。位置误差和实际消息数都要看；运行失败时，完整时段的分数会保留为无法计算。

程序会保存完整的 `evaluation.json`、汇总和轨迹 CSV。JSON 包含原策略、训练条件和种子、本次全部结果，以及测试前后的策略摘要。原文件只读，输出目录必须是新目录。

## 哪些条件可以换？

默认沿用保存时的测试设置，按新种子重新生成初始位置和外部随机输入。想改变延迟、丢包、噪声、发送上限或门槛，可把 checkpoint 中的 `evaluation_config` 保存为一个配置 JSON，再加 `--config your-config.json`。结果会记录完整配置；换了条件后，不应把差异都归因于策略。

时间步长、总时长、模型类型和输入上限要与训练时一致。步数相同也不够：60 步可能代表 1.2 秒，也可能代表 0.6 秒。这里会检查实际时间，避免把策略放进另一种时钟下运行。

新种子不能与训练或上次测试的种子重叠。这个检查只核对种子编号，并不证明各次实验在统计上独立，也不能阻止使用者反复看测试结果调参。若已经据此调整策略，应保留这些探索记录，再事先选定新的测试方案。

## 文件不对或运行失败时

- 提示使用 `policy-checkpoint.json`：旧 `policy.json` 只有 Q 表，缺少时间和来源记录，不能用于这个入口。旧表仍可用于原来的底层 Python 接口；要走这条完整流程，请用当前版本重新生成 checkpoint。
- 摘要不一致：先找回原文件。摘要用于检查文件与参数是否对应，不证明来源真实，也不认证策略质量。
- 代码版本不同：使用保存策略时的代码版本重跑，或在新版本重新训练。不要手工改摘要来消除提示。
- 初始状态超出上限：会在任何仿真开始前指出对应种子和配置问题。重新设定有依据的条件并另存记录，不能悄悄跳过难例。
- 输出目录已经存在：换一个新目录，旧结果会保留。

目前这个独立入口支持内置一阶模型。自定义模型仍用原来的 Python 接口；仅有一份 Q 表，无法证明重新加载的是同一个自定义模型。也可以在[网页中选择完整策略文件](web-recipes.md)，网页使用较小的时域和工作量范围。

## English

Run `evaluate-policy CHECKPOINT --seeds 2001,2002,2003 --out NEW_FOLDER` to test a saved built-in scalar policy without training. Use `policy-checkpoint.json`, not the legacy raw `policy.json`. The checkpoint binds the table to its physical clock, input limit, source hashes and declared seed history. Optional `--config` may change network conditions but must retain the trained plant, time step, duration and input limit. All runs and failures are retained. Checksums detect mismatches; they do not authenticate provenance or certify quality. Seed separation alone does not establish independent testing or prevent adaptive test-set reuse.
