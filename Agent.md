# Mgame-FCash-auto-tasks · Agent 接手指南

接手的是「天天领现金」里的五项每日浏览任务。启动方式见 [README](README.md)，真机结果、回测重点和日志字段见 [交接说明](交接说明.md)。

## 接手后先检查

1. 执行 `git status --short --branch`，保留工作区已有修改。离线定位故障时从已有 `runs/` 的日志、局部图和全屏截图入手。
2. 真机回测前用 `adb devices -l` 核对连接，确认手机已解锁并停在游戏首页或「每日任务」。可先运行不带 `-Execute` 的 `run.ps1` 识别当前屏幕上的任务。
3. 用户要求真机回测时，先单项跑一轮，并从手机实际进度续跑。整体验证顺序为 `page → browse12 → promo → browse14 → goods`。

```powershell
.\.venv\Scripts\python.exe -X utf8 .\fcash.py --execute --task goods --limit 1
.\.venv\Scripts\python.exe -X utf8 .\fcash.py --execute
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

## 2026-11-20 真机问题与处理

- `promo` 在 `MRNBaseActivity` 中按「特价团」标题确认新落地页。好物的新商家布局要求 `MRNStandardActivity` 与「更多推荐」「图册菜单」两个局部模板同时匹配。七猫只接受已核对的启动和更新弹窗 Activity，返回游戏时无需操作更新弹窗。
- 任务面板标题有时会在淡入的奖励浮层下匹配成功。打开面板与读取任务行均检查标题区亮度，防止暗帧进入 OCR 或供点击前定位。结算窗口内遇到 `progress_unreadable` 会取新画面重读。若重新打开面板时收下了最终奖励，该弹窗也会纳入本轮重扫结算。
- `Phone.frame` 对空数据或解码失败重取一次，ADB 明确返回设备不可用时退出。合成与领取前会再次确认游戏 Activity。若放置区合成时断线，先看 `capacity_merge`、`task_claim` 和 `stopped.last_remaining`，再确认 `adb devices -l` 显示 `device`。回到游戏后按中断任务续跑，由程序读取当前次数和待领奖状态。

本次断线前，好物最后一次读到剩余 8 次。重连后重新识别为剩余 7 次，最终续跑到 0。当天五项共完成 56 轮，五项均记录 `task_finished` 与 `remaining=0`。

## 2026-11-22 Python 执行与效率

- 定位扫描耗时时看 `task_scan_scroll` 的次数与 `wide` 字段。长滑动后会检查截图内容的方向和重叠。记录 `task_scan_narrow_retry` 时，脚本从当前画面用原短滑动重新覆盖列表。完成后的结算核对仍扫过目标行可能出现的位置。
- `progress_ocr_reused` 只复用同一任务、完全相同裁图的成功结果。`previous_ocr_ms` 是上次识别耗时，用于估算减少的 OCR 开销。需要比较总耗时，可分别统计广告等待、列表扫描和中断恢复。
- 首页额外红包广告按标题和「放弃红包奖励」两个模板关闭。微信广告仅对已核实的网页与中转 Activity 使用返回键。好物卡片的关闭图标另有不含商品背景的局部模板。
- 11 月 21 日前四项记录了 `remaining=0`。好物在第二批合成中断线。重连后回到游戏，用 `.\.venv\Scripts\python.exe -X utf8 .\fcash.py --execute --task goods` 重新读取当前次数和待领奖状态。

## 2026-11-23 真机问题与维护记录

- 11 月 22 日分段确认 56 轮全部清零，从启动到最后结算耗时 1 小时 3 分 32 秒。11 月 23 日的日常复测确认浏览页面和紫色播放清零，红包浏览 3/12。优惠活动和好物只确认了领奖。复测总耗时 1 小时 30 分 13 秒，运行日志时段合计 34 分 02 秒。
- 应用宝 Splash Activity 是广告中转，等待已确认落地页后再计时。小米应用锁先尝试系统返回。汽水音乐只在登记的两个 Activity 内走广告返回流程。未知的外跳页面保留停止诊断。
- `full_ad` 识别新的底部「立即点击」和淡色奖励提示。优惠活动仅在入口标题与按钮匹配后进入小游戏，按原停留时间分支退出。小游戏、插屏与原广告都需核对前台，原广告显示完成后才返回任务面板。
- 好物在 `MRNStandardActivity` 中用「宝藏榜」标记与标签栏，或「更多推荐」与「在线咨询」组合确认落地。21 日和 23 日的停机截图可用于回放，验证弹窗出现时由用户处理。
- 23 日的 50 红包卡片是当时明确指示的单次操作。日常合成遇到已识别的商品浮层时，使用关闭按钮恢复，先确认新画面再继续合成。

## 日常中断恢复

- `device_reconnect_wait` 最多等待 30 秒，只接受原序列号。`task_progress_reread_after_reconnect` 记录新的界面进度。若记录 `reconnect_progress_unconfirmed`，需核对断开前后的同一任务，避免重复点击。
- `verification_required` 表示需要用户在手机上核实。`task_reward_claimed_unverified` 保留领奖证据与最后读到的剩余次数，批次结果记为 `partial`。看不到任务行本身无法证明剩余 0 次。
- `home_order_offer_closed` 表示已关闭已识别的商品浮层。合成按已确认点击计数。一次 `task_scan_narrow_retry` 后，本次运行继续使用短滑动。

## 游戏主页捕捉

- 全量日常运行到批次末尾时会回到游戏主页检查捕捉，也可单独运行 `.\.venv\Scripts\python.exe -X utf8 .\fcash.py --task capture --execute`。入口有红点才打开捕捉面板，无红点即跳过。`capture_daily_panel_closed` 记录从每日任务面板返回。
- `capture_home_checked` 记录是否有红色提示。进入后先确认「幸运捕捉」，再点击橙色免费捕捉按钮一次。灰色「浏览去捕捉」和「免费升级」用于区分冷却或升级提示。查看 `capture-result` 和 `capture-cooldown` 截图核对结果。
