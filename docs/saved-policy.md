# 保存的策略，怎么拿出来再测一次？

已经做过计划复核，又想单独测一组条件后继续下个计划？用[跨流程接续历史](policy-history.md)，网页或本地命令都能保留原阶段顺序。下面的原命令行入口仍可用，它只继续兼容的已用编号列表。

想先选一个发送门槛，再用预留条件复核？可以[固定原策略再选发送方案](planned-policy.md)，不需要重跑训练。下面保留原来的单独评测流程；两条路径的初态和参考设置不同，结果不能直接混用。

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

- 选到了 `policy-history.json`：这是选择/复核流程的完整历史，请保留。若要继续原计划，回到原复核入口；若想单独测试，在原计划结果中展开“想换一组随机初态再测？”，点击“载入上方的单独测试”即可，还没有开始运行。也可以另存其中的 `policy-checkpoint.json`，完整报告 ZIP 中同样有这个文件，再用上面的命令测试。
- 提示使用 `policy-checkpoint.json`：旧 `policy.json` 只有 Q 表，缺少时间和来源记录，不能用于这个入口。旧表仍可用于原来的底层 Python 接口；要走这条完整流程，请用当前版本重新生成 checkpoint。
- 摘要不一致：先找回原文件。摘要用于检查文件与参数是否对应，不证明来源真实，也不认证策略质量。
- 代码版本不同：使用保存策略时的代码版本重跑，或在新版本重新训练。不要手工改摘要来消除提示。
- 初始状态超出上限：会在任何仿真开始前指出对应种子和配置问题。重新设定有依据的条件并另存记录，不能悄悄跳过难例。
- 输出目录已经存在：换一个新目录，旧结果会保留。

目前这个独立入口支持内置一阶模型。自定义模型仍用原来的 Python 接口；仅有一份 Q 表，无法证明重新加载的是同一个自定义模型。也可以在[网页中选择完整策略文件](web-recipes.md)，网页使用较小的时域和工作量范围。

从计划结果转来的 checkpoint 保留训练、旧评测、开发及选择/测试的全部已知编号。上面的旧命令只接续编号列表；想保留后来的完整阶段顺序，请用[完整历史接续](policy-history.md)或当前网页。单独测试按种子生成初态，并增加固定反馈等对照，不能当成原计划的固定初态复核。请保留最新完整历史和每步结果，不要回到旧文件重复使用刚测过的编号。

## English

If you selected `policy-history.json`, keep it for the planned workflow. For standalone testing, expand the alternative-testing section in the planned web result to load or save its compatible `policy-checkpoint.json`; the complete ZIP contains the same file. Loading does not run an experiment. The checkpoint retains all known used seeds, while phase names remain in the original history. Preserve both the history and the new standalone output. Standalone evaluation samples initial states by seed and adds references; it is not a rerun of the fixed-initial-state plan. New standalone results are not automatically merged into that earlier phase history.

Run `evaluate-policy CHECKPOINT --seeds 2001,2002,2003 --out NEW_FOLDER` to test a saved built-in scalar policy without training. Use `policy-checkpoint.json`, not the legacy raw `policy.json`. The checkpoint binds the table to its physical clock, input limit, source hashes and declared seed history. Optional `--config` may change network conditions but must retain the trained plant, time step, duration and input limit. All runs and failures are retained. Checksums detect mismatches; they do not authenticate provenance or certify quality. Seed separation alone does not establish independent testing or prevent adaptive test-set reuse.
