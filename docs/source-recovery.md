# 保存了文件，下次怎么接着做？

先别急着重新运行。只想看结果，完整解压当时下载的报告 ZIP，打开 `report.html` 或 `history.html`；本地服务关掉后也能看。想再计算或继续策略，才需要对应的代码和完整记录。

## JSON 输入没有读完时

如果终端提示 JSON 嵌套太深，先保留原文件，核对当前命令要用什么：实验配置、完整策略、原选择，还是已经保存的结果。回到生成它的程序，重新导出对应的完整文件，再换一个新输出目录重试。新文件仍无法读取时，保留版本、命令和错误提示，提供一份不含私人数据的小例子来定位问题。

不要手工压平 JSON、删掉阶段历史、只留下 Q 表，或提高 Python 的递归限制。这些做法不能把用途不符或不完整的文件变成可复核记录。文件用途可对照下面的表格；只想看原报告时，直接打开原 HTML 即可。

这个输入提示会列出实际文件路径和解析错误。若后面的计算或报告处理出现递归错误，终端只说明操作尚未完成，并保留原错误；不能据此判断输入太深，也不能认为已经保存了完整恢复文件。

## 算完了，报告却没能保存完整

本地选择、复核和完整历史命令会先保存一份完整计算记录。之后写报告出错或被中断时，终端会告诉你 **完整计算记录已保留**，给出实际文件位置和重绘命令。先修好磁盘空间或保存位置，再复制这条命令运行；它会使用本次的 Python，把报告写到一个新目录，不重新训练、选择方案或运行测试。

保留提示中的 `sparsiloop-recovery-...json`。它按原格式保存结果、策略与已用编号、原选择和运行环境；不要手动改摘要或把它当成一份新实验。重绘后的报告只另记这次生成报告的环境，原来未知的内容仍是未知。

如果连这份记录本身都没写成功，程序不会说已经保留了可恢复文件。先留住原输入和已有文件，检查空间与权限。报告正常写完时，备用记录会自动清理；若清理受阻，终端会列出仍保留的副本，已经完成的报告仍然有效。

这条恢复路径适用于本地命令和 Python 导出。网页临时下载没有承诺留下本地恢复文件；下载失败时先保留已有文件和页面，按错误提示处理，不要假定本次新报告已经保存。

## 按下一步选文件

| 你想做什么 | 保留并使用什么 |
| --- | --- |
| 只看原来的结果 | 整个报告 ZIP 或输出目录，保留 HTML、JSON、CSV 和轨迹 |
| 刚选完门槛，以后按原计划复核 | 原选择的完整记录：固定反馈用 `selection-bundle.json`；完整历史网页另存为 `selection-workflow.json`，本地选择输出/选择 ZIP 中叫 `policy-workflow.json` |
| 继续单独测试或做新计划 | 最新 `policy-history.json`，同时保留完整阶段 ZIP；还有待复核计划就先完成它 |
| 只有第一次训练好的策略 | 完整 `policy-checkpoint.json`；它不是 Q 表截图，也没有完整的后续阶段顺序 |
| 只重绘完整历史中的这一步 | 该阶段的 `policy-workflow.json`，不要把测试结果当成原选择 |
| 只重绘原固定反馈报告 | 原 `selection-bundle.json` 或 `test-bundle.json`；旧原始数值 JSON 仍按原入口读取 |

复核阶段的网页 ZIP 另外保留原选择 `selection-workflow.json`，当前 `policy-workflow.json` 则保存这次复核结果。只有历史或兼容 checkpoint 不能代替完整选择；程序也不会自动合并另一副本上的历史。更多文件位置见[完整历史接续](policy-history.md)。

## 把对应代码也留好

保存当时的完整发行 ZIP、`RELEASE_INFO.json` 和 `SHA256SUMS`。ZIP 内的 `BUILD_INFO.json` 写出公开仓库和**完整源码提交**，`MANIFEST.json` 列出内部文件摘要。保留输入方案、种子声明、原始输出、当时命令和自己的模型代码；私有内容放在本地，不必上传。

如果旧实验用的是开发源码，把当时完整源码单独归档，并记下实际提交及未提交改动。仅有 `sparsiloop_version` 或 `engine_version` 不能找回那份代码：早期多个开发提交都叫 `0.0.1`，数值记录里的 `engine_version` 仍表示原计算格式。来源摘要用于核对程序行为，不是一个可以反查 Git 提交的索引，也不认证来源。

已经没有源码归档或确切提交时，先查当时的下载和本地记录，明确缺失，别猜版本、改摘要或拿当前环境补过去的环境信息。自定义模型还需要自己的原实现、参数、单位及依赖；公开发行 ZIP 不会自动收集这些文件。

## 在新目录恢复

1. 核对发行页 `SHA256SUMS`，完整解压原 ZIP 到新目录；不覆盖旧项目。
2. 在 ZIP 根目录按 `START_HERE.md` 创建独立环境，离线安装随包 wheel。源码位于 `source/`；用 Git 时按 `BUILD_INFO.json` 的仓库和完整提交检出。
3. 只想重绘，不运行新仿真，在安装好原包后使用相应入口，输出到新目录：

```powershell
.\.venv\Scripts\python.exe -I -m event_control_lab.policy_journal render "old results/policy-workflow.json" --out "reports/redrawn-history"
.\.venv\Scripts\python.exe -I -m event_control_lab.planned_study render "old results/test-bundle.json" --out "reports/redrawn-planned"
```

两条是不同格式的示例，选择与你的文件对应的一条。重绘保留原数值、失败与原执行环境，只另外记录这次生成报告的环境；不会重新训练或运行种子。只有 checkpoint 而没有原结果，无法重建当时的完整轨迹。

继续实验时，复核仍用原选择和预留编号；新任务用最新完整历史及新编号。遇到源码、参数、Q 表或时钟不匹配就停在运行前核对原文件，不删历史、不改摘要绕过。结果一致也不能证明硬件效果、统计独立或跨平台逐位相同。

## English

If JSON nesting prevents an input from being read, keep the original. Check whether the command needs a configuration, complete policy, original choice or saved result, then re-export that complete file from its generating program and retry into a new output directory. Do not flatten JSON, remove history, keep only the Q table, or raise Python's recursion limit. If it still fails, retain the version, command and error with a small non-private example. Existing HTML can be read without loading a JSON file.

The input message identifies the file and original parser error. A later recursion error in computation or report processing is reported as an incomplete operation; it does not establish excessive input nesting or confirm a complete recovery copy.

Keep the complete report ZIP, original choice, latest history, configuration and matching source archive. Read existing HTML directly. Repeat a planned test with its original complete choice; start a new task with the latest complete history after resolving pending tests. A checkpoint or Q table cannot recreate missing trajectories, and a test result is not a selection record.

The release ZIP contains exact public source, `BUILD_INFO.json` and a per-member manifest. Keep its release information and checksums as well. Package versions, legacy `engine_version` and behavior fingerprints cannot identify an unrecorded development checkout. Archive custom model code and dependencies yourself; no private files are automatically collected. Use a fresh environment and output folder. The two `render` examples above only redraw their respective saved formats; they do not train or simulate, fill missing history, or replace unknown execution environments. Checksums and declared histories establish consistency, not authenticated origin, independence or stability.

Local planned/history exports retain a complete typed recovery record before rendering. A later I/O failure or interruption prints the actual file and a redraw command using the current interpreter. Fix the save location and run that command into a new folder; it does not rerun training, selection or tests. Keep the recovery file and original input. A failed initial recovery write is not advertised as recoverable. Successful exports remove the temporary recovery copy unless cleanup is blocked, in which case the complete report remains valid and the retained copy is reported. This local-file contract does not apply to ephemeral web-download staging.
