# Mgame-FCash-auto-tasks

Windows 上的「领现金」每日任务助手。通过 USB 在已授权的 Android 手机上依次完成已核对的五项浏览任务。程序从手机界面读取进度，按剩余次数续跑。

## 手机和电脑怎么准备

1. 手机开启 USB 调试，用数据线连接电脑并解锁。接受手机上的调试授权，保持 1080×2400 竖屏。使用小米手机时，如果截图能读到但点击无响应，再检查「USB 调试（安全设置）」。
2. 手机打开「天天领现金」，停在游戏首页或右下角「任务」打开的「每日任务」。
3. 在 Windows 安装 Android Platform Tools 和简体中文 OCR。用 `adb devices -l` 核对连接。在仓库根目录准备 Python 环境。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```powershell
# 只识别当前可见任务
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1

# 按顺序执行剩余任务
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Execute
```

只有一台已授权真机时会自动选择。多台手机时加 `-Serial <序列号>`。可用 `-Python <解释器路径>` 指定已有 Python，或加 `-Task goods -Limit 1` 单独试跑一轮。

| 顺序 | 参数 | 任务 |
|---|---|---|
| 1 | `page` | 浏览页面领奖励 |
| 2 | `browse12` | 完成浏览领奖励（红包图标） |
| 3 | `promo` | 浏览优惠活动 |
| 4 | `browse14` | 完成浏览领奖励（紫色播放图标） |
| 5 | `goods` | 浏览好物 5 秒领奖励 |

放置区满时，程序会回游戏首页，间隔 5.5 秒执行 10 次一键合成，再打开「每日任务」。如果停在未知页面，先查看窗口里的停止原因和运行记录，再从游戏首页或任务列表续跑。

维护入口见 [Agent.md](Agent.md) 和 [交接说明](交接说明.md)。
