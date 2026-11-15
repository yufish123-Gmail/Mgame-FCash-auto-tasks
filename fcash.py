from __future__ import annotations

import argparse
import json
import msvcrt
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent
MEITUAN = "com.sankuai.meituan"
GAME = "com.meituan.android.mgc.container.MGCGameActivity"
MAIN = MEITUAN + "/com.meituan.android.pt.homepage.activity.MainActivity"
WEB = "com.meituan.android.knb.core.StandardKnbActivity"
TITANS_WEB = "com.sankuai.titans.adapter.mtapp.KNBWebViewActivity"
DEAL_DETAIL = "com.meituan.android.generalcategories.dealdetail.GCDealDetailActivity"
SUBGAME = GAME + "1"
FULL_AD = MEITUAN + ".msv.page.activity.MSVPageActivity"
# These apps were already verified as ad destinations in the local Meituan setup.
AD_APPS = {
    "com.taobao.taobao", "com.android.browser", "com.alibaba.wireless", "com.kuaishou.nebula",
    "com.tmall.wireless", "com.baidu.netdisk", "com.aliyun.tongyi", "com.baidu.BaiduMap",
    "com.qiyi.video", "com.UCMobile", "com.dianping.v1", "com.xunmeng.pinduoduo", "cn.missevan",
    "com.xiaomi.market", "com.fenxiang.storyline", "com.sina.weibo", "com.jingdong.app.mall",
}
LIST = (28, 1081, 1050, 2379)


@dataclass(frozen=True)
class Task:
    key: str
    name: str
    title: str
    total: int | None
    icon: str | None = None


TASKS = (
    Task("page", "浏览页面领奖励", "page", 12),
    Task("browse12", "完成浏览领奖励（红包）", "browse", 12, "icon_red"),
    Task("promo", "浏览优惠活动", "promo", 10),
    Task("browse14", "完成浏览领奖励（紫色播放）", "browse", 14, "icon_purple"),
    Task("goods", "浏览好物5秒领奖励", "goods", None),
)


class Stop(RuntimeError):
    pass


def command(*args):
    result = subprocess.run(args, capture_output=True, timeout=20)
    if result.returncode:
        raise Stop(result.stderr.decode("utf-8", errors="replace").strip() or f"命令失败，退出码 {result.returncode}。")
    return result.stdout


def crop(image, box):
    x1, y1, x2, y2 = box
    return image[y1:y2, x1:x2]


def center(box):
    x1, y1, x2, y2 = box
    return (x1 + x2) // 2, (y1 + y2) // 2


def save(path, image):
    encoded, data = cv2.imencode(".png", image)
    if encoded:
        path.write_bytes(data.tobytes())


class Phone:
    def __init__(self, serial=None):
        local = os.environ.get("LOCALAPPDATA", "")
        candidate = Path(local) / "Android/Sdk/platform-tools/adb.exe"
        self.adb = shutil.which("adb") or (str(candidate) if local and candidate.is_file() else None)
        if not self.adb:
            raise Stop("找不到 adb，请检查 Android Platform Tools。")
        rows = command(self.adb, "devices", "-l").decode(errors="replace").splitlines()
        devices = [
            fields[0] for fields in map(str.split, rows)
            if len(fields) > 2 and fields[1] == "device"
            and any(field.startswith(("usb:", "transport_id:")) for field in fields[2:])
            and not fields[0].startswith("emulator-")
            and ":" not in fields[0] and not fields[0].endswith("._adb-tls-connect._tcp")
        ]
        if serial is None:
            if len(devices) != 1:
                raise Stop("请连接并授权一台 USB 真机。连接多台时请用 -Serial 指定。")
            serial = devices[0]
        if serial not in devices:
            raise Stop(f"未找到已授权的手机 {serial}。")
        self.serial = serial

    def call(self, *args):
        return command(self.adb, "-s", self.serial, *args)

    def component(self):
        out = self.call("shell", "dumpsys", "activity", "activities").decode(errors="replace")
        match = re.search(r"(?:topResumedActivity=|mResumedActivity:).*?\s([\w.]+)/([\w.$]+)", out)
        if not match:
            return None, None
        package, activity = match.groups()
        return package, package + activity if activity.startswith(".") else activity

    def frame(self):
        data = self.call("exec-out", "screencap", "-p")
        if not data:
            raise Stop("手机截图不可用，请确认已解锁。")
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != (2400, 1080):
            raise Stop("请保持手机 1080×2400 竖屏。")
        return image

    def tap(self, box):
        if self.component()[0] != MEITUAN:
            raise Stop("点击前美团已离开前台。")
        self.call("shell", "input", "tap", *map(str, center(box)))

    def scroll(self, down):
        if self.component() != (MEITUAN, GAME):
            raise Stop("滚动前未确认游戏在前台。")
        start, end = (2180, 1600) if down else (1500, 2130)
        self.call("shell", "input", "swipe", "475", str(start), "475", str(end), "800")
        time.sleep(1.0)

    def back(self):
        self.call("shell", "input", "keyevent", "KEYCODE_BACK")

    def return_to_game(self, *, main=False):
        self.call("shell", "am", "start", "-a", "android.intent.action.MAIN", "-c",
                  "android.intent.category.LAUNCHER", "-f", "0x34000000" if main else "0x10200000", "-n", MAIN)


class Runner:
    def __init__(self, phone):
        self.phone = phone
        self.run = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.run.mkdir(parents=True)
        self.final_rewards = 0
        self.capacity_recoveries = 0
        self.blocked = False
        self.templates = {
            p.stem: cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
            for p in (ROOT / "templates").glob("*.png")
        }

    def log(self, event, **fields):
        with (self.run / "events.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "event": event, **fields},
                                  ensure_ascii=False) + "\n")

    def match(self, image, name, region, threshold=0.91):
        template = self.templates[name]
        box = cv2.cvtColor(crop(image, region), cv2.COLOR_BGR2GRAY)
        height, width = template.shape
        if min(box.shape) == 0 or height > box.shape[0] or width > box.shape[1]:
            return None
        _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(box, template, cv2.TM_CCOEFF_NORMED))
        if score >= threshold:
            x, y = x + region[0], y + region[1]
            return (x, y, x + width, y + height)
        return None

    def panel(self):
        deadline = time.monotonic() + 20
        next_open = 0.0
        open_attempts = 0
        merged = False
        while time.monotonic() < deadline:
            if self.phone.component() == (MEITUAN, GAME):
                image = self.phone.frame()
                if self.match(image, "capacity", (170, 1120, 919, 1270), 0.87):
                    if merged:
                        raise Stop("已合成 10 次，游戏仍提示放置区角色已达上限。")
                    self.merge_for_capacity(image)
                    merged = True
                    next_open = 0.0
                    open_attempts = 0
                    deadline = time.monotonic() + 20
                    continue
                if self.match(image, "reward", (220, 390, 860, 620)):
                    later = self.match(image, "later", (90, 1570, 490, 1800), 0.81)
                    final = self.match(image, "final", (350, 1570, 730, 1800))
                    if not (later or final):
                        time.sleep(0.45)
                        continue
                    self.phone.tap(later or final)
                    if final:
                        self.final_rewards += 1
                    self.log("reward_dismissed", final=bool(final))
                elif self.match(image, "offline", (272, 385, 815, 565)):
                    close = self.match(image, "offline_close", (303, 1800, 772, 1969))
                    if not close:
                        raise Stop("离线收益浮层遮住任务入口，未识别跳过按钮。")
                    self.phone.tap(close)
                elif self.match(image, "panel", (365, 685, 716, 834)):
                    return image
                elif open_attempts < 3 and time.monotonic() >= next_open:
                    entry = self.match(image, "task_entry", (750, 2060, 905, 2260), 0.86)
                    if entry:
                        x = center(entry)[0]
                        y = entry[1] - 34
                        self.phone.tap((x, y, x, y))
                        self.log("task_panel_tap", point=(x, y))
                        open_attempts += 1
                        next_open = time.monotonic() + 4
            time.sleep(0.4)
        raise Stop("未确认「领现金 → 每日任务」。")

    def merge_for_capacity(self, image):
        if self.match(image, "panel", (365, 685, 716, 834)):
            close = self.match(image, "panel_close", (950, 676, 1060, 800))
            if not close:
                raise Stop("放置区已满，但每日任务面板关闭按钮未确认。")
            self.phone.tap(close)
            time.sleep(0.7)
        print("放置区已满，按 5.5 秒间隔执行 10 次一键合成。", flush=True)
        for step in range(10):
            if self.phone.component() != (MEITUAN, GAME):
                raise Stop("一键合成期间已离开领现金游戏。")
            image = self.phone.frame()
            entry = self.match(image, "task_entry", (750, 2060, 905, 2260), 0.86)
            button = self.match(image, "merge", (915, 1680, 1062, 1850), 0.85)
            if not (entry and button):
                raise Stop("未确认游戏首页的「一键合成」按钮。")
            self.phone.tap(button)
            self.log("capacity_merge", step=step + 1)
            time.sleep(5.5)
        self.capacity_recoveries += 1

    def row(self, image, task):
        top = LIST[1]
        while top < 2340:
            title = self.match(image, task.title, (227, top, 610, 2345))
            if not title:
                return None
            y = title[1]
            top = y + 68
            if y + 118 > LIST[3]:
                return None
            if task.icon and not self.match(image, task.icon, (65, max(LIST[1], y - 32), 200, y + 132), 0.84):
                continue
            button = self.match(image, "go", (806, y - 22, 1002, min(2380, y + 112)))
            if button:
                return title, button
            # A visible row without a Go button can carry a completed count.
            return title, None
        return None

    def find(self, task, image):
        for down in (False, True):
            still = 0
            for _ in range(24):
                row = self.row(image, task)
                if row:
                    return image, row
                old = crop(image, LIST)
                self.phone.scroll(down)
                image = self.panel()
                current = crop(image, LIST)
                still = still + 1 if cv2.norm(old, current, cv2.NORM_L1) / current.size < 1.55 else 0
                if still >= 2:
                    break
        return image, None

    def ocr(self, image, filename):
        path = self.run / filename
        save(path, image)
        return command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                       str(ROOT / "read-progress.ps1"), "-Image", str(path)).decode("utf-8", errors="replace").strip()

    def remaining(self, image, task, title):
        y = title[1]
        gray = cv2.cvtColor(crop(image, (225, y - 3, 782, y + 59)), cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)
        for style in (gray, binary):
            enlarged = cv2.resize(style, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            padded = cv2.copyMakeBorder(enlarged, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
            raw = self.ocr(padded, f"progress-{task.key}.png")
            value = re.sub(r"\s+", "", raw).replace("／", "/")
            if task.total is None:
                # The row title is already verified visually. Read only its trailing count.
                match = re.search(r"(\d{1,2})次[)）]?$", value)
                if match and int(match[1]) <= 30:
                    return int(match[1])
            else:
                match = re.search(rf"(\d{{1,2}})/{task.total}(?!\d)", value)
                if match and int(match[1]) <= task.total:
                    return task.total - int(match[1])
        raise Stop(f"无法确认「{task.name}」进度，识别结果 {raw!r}。")

    def ad_button(self, image):
        if not self.match(image, "ad_close", (479, 1680, 603, 1905), 0.85):
            return None
        known = self.match(image, "ad5", (260, 1390, 817, 1625))
        if known:
            return known, 5
        for y in (1552, 1521, 1493):
            pixels = crop(image, (172, y - 44, 906, y + 44))
            blue, green, red = cv2.split(pixels)
            if np.mean((red > 200) & (green > 162) & (blue < 130)) < 0.65:
                continue
            words = re.sub(r"\s+", "", self.ocr(pixels, "ad-instruction.png"))
            match = re.fullmatch(r"点击并浏览(3|5|10|15|20|30)秒领奖励", words)
            if match:
                return (172, y - 44, 906, y + 44), int(match[1])
        return None

    def open_round(self, task):
        deadline = time.monotonic() + 13
        while time.monotonic() < deadline:
            package, activity = self.phone.component()
            if package == MEITUAN:
                image = self.phone.frame()
                if task.key == "goods" and self.goods_card_button(image):
                    return self.browse_goods_card(image)
                button = self.ad_button(image)
                if button:
                    self.phone.tap(button[0])
                    self.log("ad_opened", task=task.key, seconds=button[1])
                    return self.browse_landing(button[1])
                if activity == FULL_AD:
                    return self.full_ad()
                if task.key == "promo" and activity == SUBGAME:
                    self.log("promo_subgame", seconds=12)
                    time.sleep(12)
                    return self.leave_subgame()
                if task.key == "promo" and activity == WEB:
                    return self.browse_internal(activity, 10)
                if (task.key == "promo" and activity == "com.meituan.android.mrn.container.MRNBaseActivity"
                    and self.match(image, "merchant", (555, 2210, 820, 2330))):
                    return self.browse_internal(activity, 10)
                if (task.key == "goods" and activity == "com.meituan.android.mrn.container.MRNBaseActivity"
                    and self.match(image, "goods_landing", (191, 115, 902, 278))):
                    return self.browse_internal(activity, 5)
                if (task.key == "goods" and activity == "com.meituan.android.mrn.container.MRNBaseActivity"
                    and self.match(image, "goods_refund", (170, 110, 902, 260), 0.88)):
                    time.sleep(7)
                    if self.phone.component() == (MEITUAN, activity):
                        close = self.match(self.phone.frame(), "goods_refund_close", (470, 1730, 609, 1860), 0.87)
                        if close:
                            self.phone.tap(close)
                            time.sleep(0.5)
                        self.phone.back()
                    return self.panel()
            time.sleep(0.5)
        raise Stop(f"「{task.name}」未识别到广告按钮或已验证的落地页。")

    def goods_card_button(self, image):
        if self.match(image, "goods_card", (108, 1190, 485, 1350)):
            return self.match(image, "goods_card_button", (359, 1520, 768, 1712))
        return None

    def browse_goods_card(self, image):
        button = self.goods_card_button(image)
        if not button:
            raise Stop("未确认惊喜特价卡片的「浏览5s领奖励」。")
        time.sleep(0.7)
        button = self.goods_card_button(self.phone.frame())
        if not button:
            raise Stop("惊喜特价卡片在点击前已变化。")
        self.phone.tap(button)
        deadline = time.monotonic() + 20
        retry_at = time.monotonic() + 4
        retries = 0
        while time.monotonic() < deadline:
            package, activity = self.phone.component()
            if package == MEITUAN and activity in {WEB, TITANS_WEB, DEAL_DETAIL, "com.meituan.android.mrn.container.MRNBaseActivity"}:
                self.log("goods_card_landing", activity=activity, seconds=7)
                time.sleep(7)
                if self.phone.component() == (MEITUAN, activity):
                    self.phone.back()
                    time.sleep(1.2)
                if self.phone.component() == (MEITUAN, GAME):
                    current = self.phone.frame()
                    if self.goods_card_button(current):
                        close = self.match(current, "goods_card_close", (878, 585, 1007, 712))
                        if not close:
                            raise Stop("未确认浏览卡片关闭按钮。")
                        self.phone.tap(close)
                return self.panel()
            if package in AD_APPS:
                return self.browse_landing(5)
            if (package, activity) == (MEITUAN, GAME) and retries < 2 and time.monotonic() >= retry_at:
                button = self.goods_card_button(self.phone.frame())
                if button:
                    self.phone.tap(button)
                    retries += 1
                    retry_at = time.monotonic() + 4
                    self.log("goods_card_retry", attempt=retries)
            time.sleep(0.45)
        raise Stop("打开好物浏览卡片后未识别落地页。")

    def full_ad(self):
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            if self.phone.component() != (MEITUAN, FULL_AD):
                break
            image = self.phone.frame()
            if self.match(image, "full_done", (95, 156, 485, 254), 0.81):
                self.log("full_ad_confirmed")
                self.phone.back()
                time.sleep(1.3)
                return self.panel()
            replay = self.match(image, "replay", (390, 1440, 690, 1590), 0.83)
            instruction = self.match(image, "full_instruction", (90, 159, 472, 255), 0.80)
            if replay and instruction:
                region = (416, 1325, 653, 1431)
                button = self.match(image, "full_open", region, 0.88) or self.match(image, "full_click", region, 0.88)
                if not button:
                    region = (384, 1340, 697, 1420)
                    pixels = crop(image, region)
                    blue, green, red = cv2.split(pixels)
                    if np.mean((red > 190) & (green > 155) & (blue < 140)) > 0.68:
                        title = re.sub(r"\s+", "", self.ocr(pixels, "full-ad-button.png"))
                        if title in {"立即点击", "立即打开", "立即体验"}:
                            button = region
                if not button:
                    raise Stop("全屏广告要求打开落地页，但未确认入口按钮。")
                self.phone.tap(button)
                return self.browse_landing(10, from_full=True)
            time.sleep(0.8)
        raise Stop("未确认全屏广告已播放结束。")

    def leave_subgame(self):
        for _ in range(3):
            component = self.phone.component()
            if component == (MEITUAN, GAME):
                return self.panel()
            if component != (MEITUAN, SUBGAME):
                break
            image = self.phone.frame()
            if self.match(image, "update_prompt", (400, 1002, 685, 1162)):
                button = self.match(image, "update_cancel", (186, 1286, 509, 1396))
            else:
                button = self.match(image, "subgame_exit", (920, 36, 1045, 165), 0.86)
            if not button:
                break
            self.phone.tap(button)
            time.sleep(1.1)
        if self.phone.component() == (MEITUAN, SUBGAME):
            self.phone.return_to_game(main=True)
            self.log("subgame_reopen_from_profile")
            time.sleep(12)
            image = self.phone.frame()
            entry = self.match(image, "profile_game", (280, 1750, 558, 2010))
            if not entry:
                raise Stop("退出子游戏后未找到美团「我的」中的「天天领现金」。")
            self.phone.tap(entry)
        return self.panel()

    def browse_landing(self, seconds, *, from_full=False):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            package, activity = self.phone.component()
            if not from_full and (package, activity) == (MEITUAN, FULL_AD):
                return self.full_ad()
            if (package, activity) == (MEITUAN, WEB):
                return self.browse_internal(activity, seconds)
            if (package, activity) == ("com.miui.securitycenter", "com.miui.applicationlock.ConfirmAccessControl"):
                self.log("app_lock_return")
                self.blocked = True
                self.phone.return_to_game()
                time.sleep(1.3)
                if self.phone.component()[0] == MEITUAN:
                    image = self.phone.frame()
                    if self.ad_button(image):
                        close = self.match(image, "ad_close", (479, 1680, 603, 1905), 0.85)
                        if close:
                            self.phone.tap(close)
                return self.panel()
            if package in AD_APPS:
                self.log("landing", package=package, activity=activity)
                time.sleep(seconds + 2)
                if self.phone.component()[0] not in AD_APPS:
                    raise Stop("广告停留期间页面发生切换。")
                self.phone.return_to_game()
                time.sleep(1.3)
                if from_full and self.phone.component() == (MEITUAN, FULL_AD):
                    image = self.phone.frame()
                    if not self.match(image, "full_done", (95, 156, 485, 254), 0.81):
                        raise Stop("广告落地页返回后未显示「已完成，返回领奖励」。")
                    self.phone.back()
                    time.sleep(1.3)
                return self.panel()
            if package not in (None, MEITUAN):
                raise Stop(f"广告跳转到尚未验证的应用 {package}。")
            time.sleep(0.5)
        raise Stop("广告打开后未识别落地页，尚未确认浏览计时。")

    def browse_internal(self, activity, seconds):
        self.log("landing", package=MEITUAN, activity=activity, seconds=seconds)
        time.sleep(seconds + 2)
        for _ in range(2):
            if self.phone.component() != (MEITUAN, activity):
                break
            self.phone.back()
            time.sleep(1.2)
        return self.panel()

    def settlement(self, image, task, left, final_before):
        deadline = time.monotonic() + 10
        after = None
        claimed = False
        while True:
            row = self.row(image, task)
            if left == 1 and self.final_rewards > final_before:
                return image, row, 0
            if row:
                if not claimed:
                    reward_result = self.collect_ready(image, task, row)
                    if reward_result is not None:
                        claimed = True
                        image = reward_result
                        continue
                after = self.remaining(image, task, row[0])
                if after != left:
                    return image, row, after
            if time.monotonic() >= deadline:
                if row:
                    return image, row, after
                image, row = self.find(task, image)
                if left == 1 and self.final_rewards > final_before:
                    return image, row, 0
                if row:
                    return image, row, self.remaining(image, task, row[0])
                raise Stop(f"浏览后未找到「{task.name}」，无法核对结算。")
            time.sleep(0.55)
            image = self.panel()

    def claim_ready(self, image, task, row):
        if task.key != "goods" or row[1]:
            return False
        y = row[0][1]
        button = self.match(image, "claim", (805, max(LIST[1], y - 24), 1006, min(2380, y + 115)))
        if not button:
            return False
        self.phone.tap(button)
        self.log("task_claim", task=task.key)
        time.sleep(1.4)
        return True

    def collect_ready(self, image, task, row):
        capacity_before = self.capacity_recoveries
        if not self.claim_ready(image, task, row):
            return None
        image = self.panel()
        if self.capacity_recoveries > capacity_before:
            image, row = self.find(task, image)
            if row and self.claim_ready(image, task, row):
                image = self.panel()
        return image

    def finish(self, task, limit):
        image, row = self.find(task, self.panel())
        if row is None:
            self.log("task_not_listed", task=task.key)
            print(f"当前列表未显示「{task.name}」，跳过。", flush=True)
            return
        final_before = self.final_rewards
        claimed_image = self.collect_ready(image, task, row)
        if claimed_image is not None:
            image, row = self.find(task, claimed_image)
            if row is None:
                if self.final_rewards > final_before:
                    self.log("task_finished", task=task.key, remaining=0)
                    print(f"{task.name}：最终奖励已结算。", flush=True)
                    return
                raise Stop("领取好物奖励后未确认任务状态。")
        left = self.remaining(image, task, row[0])
        print(f"{task.name}：剩余 {left} 次。", flush=True)
        self.log("task_started", task=task.key, remaining=left)
        rounds = min(left, limit) if limit else left
        retries = 0
        while rounds > 0:
            if row[1] is None:
                raise Stop(f"「{task.name}」仍有剩余，但未看到「去完成」。")
            current = self.panel()
            fresh = self.row(current, task)
            if not fresh or fresh[1] is None:
                raise Stop("点击前任务行已变化。")
            if abs(fresh[1][1] - row[1][1]) > 12 and self.remaining(current, task, fresh[0]) != left:
                raise Stop("点击前移动后的任务进度已变化。")
            for _ in range(5):
                time.sleep(0.6)
                stable = self.phone.frame()
                checked = self.row(stable, task)
                if not checked or checked[1] is None:
                    continue
                if abs(checked[1][1] - fresh[1][1]) <= 5:
                    break
                fresh = checked
            else:
                raise Stop("列表仍在移动，未点击任务。")
            y = checked[0][1]
            save(self.run / f"row-{task.key}-{left}-{retries}.png", crop(stable, (53, y - 23, 1038, y + 100)))
            self.phone.tap(checked[1])
            self.log("task_tap", task=task.key, point=center(checked[1]))
            final_before = self.final_rewards
            self.blocked = False
            image, row, after = self.settlement(self.open_round(task), task, left, final_before)
            if after == left and self.blocked and retries < 3:
                retries += 1
                self.log("blocked_retry", task=task.key, remaining=left)
                continue
            if after != left - 1:
                raise Stop(f"「{task.name}」剩余次数未按预期变化（{left} → {after}）。")
            self.log("round_confirmed", task=task.key, remaining=after)
            print(f"{task.name}：本轮已结算，剩余 {after} 次。", flush=True)
            left = after
            rounds -= 1
            retries = 0
        self.log("task_finished" if left == 0 else "limit_reached", task=task.key, remaining=left)


def main():
    parser = argparse.ArgumentParser(description="领现金 · 每日任务浏览助手")
    parser.add_argument("--serial", help="已授权 USB 真机的 ADB 序列号")
    parser.add_argument("--task", choices=("all", *(task.key for task in TASKS)), default="all")
    parser.add_argument("--limit", type=int, default=0, help="每项最多执行的轮数，0 表示完成剩余轮数")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume-ad", action="store_true", help="继续当前已确认归属的全屏广告")
    args = parser.parse_args()
    if args.resume_ad and (not args.execute or args.task == "all"):
        parser.error("--resume-ad requires --execute and a specific --task")
    runner = None
    try:
        with (ROOT / "session.lock").open("a+b") as lock:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            runner = Runner(Phone(args.serial))
            tasks = [task for task in TASKS if args.task in {"all", task.key}]
            if args.resume_ad:
                frame = runner.phone.frame()
                if args.task == "goods" and runner.goods_card_button(frame):
                    runner.browse_goods_card(frame)
                else:
                    runner.full_ad()
            if not args.execute:
                image = runner.phone.frame()
                for task in tasks:
                    row = runner.row(image, task)
                    if row:
                        print(f"{task.name}：识别到行，剩余 {runner.remaining(image, task, row[0])} 次。")
                return 0
            for task in tasks:
                runner.finish(task, args.limit)
        return 0
    except (Stop, OSError, subprocess.TimeoutExpired, cv2.error) as exc:
        if runner:
            runner.log("stopped", reason=str(exc))
        print(f"已停止：{exc}", file=sys.stderr)
        return 2
    finally:
        if runner:
            print(f"运行记录：{runner.run}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
