# Mgame-FCash-auto-tasks · Agent 接手指南

接手的是「天天领现金」里的五项每日浏览任务。启动方式见 [README](README.md)，真机结果、回测重点和日志字段见 [交接说明](交接说明.md)。

## 接手后先检查

1. 执行 `git status --short --branch`，保留工作区已有修改。离线定位故障时从已有 `runs/` 的日志、局部图和全屏截图入手。
2. 真机回测前用 `adb devices -l` 核对连接，确认手机已解锁并停在游戏首页或「每日任务」。可先运行不带 `-Execute` 的 `run.ps1` 识别当前屏幕上的任务。
3. 用户要求真机回测时，先单项跑一轮，并从手机实际进度续跑。整体验证顺序为 `page → browse12 → promo → browse14 → goods`。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Task goods -Limit 1 -Execute
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Execute
```

## 改哪里、怎么验证

- `Runner.panel` 核对每日任务面板并处理奖励弹窗。`merge_for_capacity` 在确认放置区满时按 5.5 秒间隔合成 10 次，`collect_ready` 检查容量恢复后是否仍有同一行待领奖。
- `Runner.row`、`find`、`remaining` 确认标题、图标、按钮和次数。`open_round` 处理广告流程分支，`settlement` 核对次数变化和最终奖励。加规则时先用截图与前台活动确认落地页和退出方式。奖励只能按原任务行及实际弹窗确认。
- 停止后按交接说明中的诊断流程核对 `stopped`、`diagnostics_finished` 和当轮截图，再根据实际剩余次数续跑。准备提交时运行 `git diff --check` 和 `python -m py_compile fcash.py`，再验证对应识别规则。提交包含必要的局部模板，原始截屏、运行日志和本机环境留在本地。

## 2026-11-19 真机复测与续跑

五项共 56 轮，按上述顺序分别完成 12、12、10、14 和 8 轮。期间遇到 USB 掉线、广告页切换和识别中断，按手机上的实际剩余次数分段续跑。五项均记录了 `task_finished` 和 `remaining=0`。

- 外部广告落地页按实测的前台应用或 Activity 确认。抖音跳转页和小米云服务过渡页仅等待页面切换。遇到应用锁时回到游戏，若随后出现已确认的浏览器落地页，再按浏览时间和前台状态处理。
- 全屏广告的入口按钮晚于「重新播放」出现时，`full_ad` 最多重识别 5 秒。点击后如仍停在全屏广告页，先观察落地页是否启动。返回时通过完成提示确认退出。
- 好物卡片先匹配标题或关闭按钮，再确认浏览按钮。站内团购和商家页按 Activity 与页面特征确认。遇到「团购信息获取失败」时返回列表，按同一任务行的实际进度决定是否重试。
- 仍停在由本程序打开、归属明确的落地页时，可用 `.\.venv\Scripts\python.exe fcash.py --execute --task goods --recover-landing` 续跑。归属明确的全屏广告仍在前台时，可用 `.\.venv\Scripts\python.exe fcash.py --execute --task browse14 --resume-ad`。任务 ID 按实际中断位置填写。
