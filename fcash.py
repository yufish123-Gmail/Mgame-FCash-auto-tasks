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
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent
MEITUAN = "com.sankuai.meituan"
GAME = "com.meituan.android.mgc.container.MGCGameActivity"
MAIN = MEITUAN + "/com.meituan.android.pt.homepage.activity.MainActivity"
MAIN_COMPONENT = tuple(MAIN.split("/", 1))
WEB = "com.meituan.android.knb.core.StandardKnbActivity"
TITANS_WEB = "com.sankuai.titans.adapter.mtapp.KNBWebViewActivity"
MRN = "com.meituan.android.mrn.container.MRNBaseActivity"
MRN_STANDARD = "com.meituan.android.mrn.container.MRNStandardActivity"
MRNX = "com.meituan.android.mrnx.container.MRNXStandardActivity"
TRAVEL_DETAIL = "com.meituan.traveltools.mrncontainer.HTMRNBaseActivity"
DEAL_DETAIL = "com.meituan.android.generalcategories.dealdetail.GCDealDetailActivity"
SUBGAME = GAME + "1"
FULL_AD = MEITUAN + ".msv.page.activity.MSVPageActivity"
AD_WEB = "com.ubix.ssp.open.comm.UBiXWebViewActivity"
AD_SHOP = "com.qq.e.ads.ADActivity"
WECHAT_AD_WEB_VIEWS = {
    ("com.tencent.mm", "com.tencent.mm.plugin.webview.ui.tools.CustomSchemeEntryMMWebViewUI"),
    ("com.tencent.mm", "com.tencent.mm.plugin.webview.stub.WebViewStubProxyUI"),
}
CLOUD_HANDOFF = ("com.miui.cloudservice", "com.miui.cloudservice.wxapi.WXEntryActivity")
DOUYIN_HANDOFF = ("com.ss.android.ugc.aweme", "com.ss.android.ugc.aweme.app.DeepLinkHandlerActivity")
APP_LOCK = ("com.miui.securitycenter", "com.miui.applicationlock.ConfirmAccessControl")
AD_LANDING_COMPONENTS = {
    ("com.taobao.idlefish", "com.taobao.fleamarket.home.activity.InitActivity"),
    ("com.taobao.idlefish", "com.taobao.idlefish.custom.FishUserLoginActivity"),
    ("com.ss.android.article.lite", "com.ss.android.article.base.feature.app.schema.AdsAppActivity"),
    ("com.ss.android.article.lite", "com.ss.android.ugc.detail.activity.TikTokActivity"),
    ("com.quark.browser", "com.ucpro.MainActivity"),
    ("com.quark.browser", "com.ucpro.BrowserActivity"),
    ("com.miui.video", "com.miui.video.app.IntentActivity"),
    ("com.miui.video", "com.miui.video.feature.home.VideoFlowPlayLetActivity"),
    ("com.kmxs.reader", "com.km.app.home.view.LoadingActivity"),
    ("com.kmxs.reader", "com.km.app.update.UpdateVersionV2Activity"),
}
# These apps were already verified as ad destinations in the local Meituan setup.
AD_APPS = {
    "com.eg.android.AlipayGphone", "com.tencent.mm",
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
    def __init__(self, message, *, code=None):
        super().__init__(message)
        self.code = code


class DifferentTotal(Stop):
    pass


def is_ad_landing(component):
    return component[0] in AD_APPS or component in AD_LANDING_COMPONENTS


def command(*args, timeout=20):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise Stop(result.stderr.decode("utf-8", errors="replace").strip() or f"命令失败，退出码 {result.returncode}。")
    return result.stdout


def crop(image, box):
    x1, y1, x2, y2 = box
    return image[y1:y2, x1:x2]


def center(box):
    x1, y1, x2, y2 = box
    return (x1 + x2) // 2, (y1 + y2) // 2


def panel_header_visible(image):
    # The title template also matches through a modal fade.
    header = crop(image, (360, 701, 720, 724))
    return np.median(header[:, :, 2]) >= 180


def list_frames_overlap(before, after, down):
    # Keep enough shared content to see a full row across the two viewports.
    before = cv2.resize(before[:, 50:860], None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    after = cv2.resize(after[:, 50:860], None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    height = before.shape[0]
    sample_height = 132
    start = height - 55 - sample_height if down else 55
    scores = cv2.matchTemplate(after, before[start:start + sample_height], cv2.TM_CCOEFF_NORMED)
    _, score, _, (_, end) = cv2.minMaxLoc(scores)
    shift = end - start
    distance = -shift if down else shift
    if score < 0.94 or not 0 <= distance <= 390:
        return False
    old_start, new_start = max(0, -shift), max(0, shift)
    shared_height = height - abs(shift)
    old_region = before[old_start:old_start + shared_height]
    new_region = after[new_start:new_start + shared_height]
    return cv2.norm(old_region, new_region, cv2.NORM_L1) / old_region.size < 8


def save(path, image):
    encoded, data = cv2.imencode(".png", image)
    if not encoded:
        raise Stop("截图编码失败。", code="screenshot_encode_failed")
    path.write_bytes(data.tobytes())


class Phone:
    def __init__(self, serial=None):
        local = os.environ.get("LOCALAPPDATA", "")
        candidate = Path(local) / "Android/Sdk/platform-tools/adb.exe"
        self.adb = shutil.which("adb") or (str(candidate) if local and candidate.is_file() else None)
        if not self.adb:
            raise Stop("找不到 adb，请检查 Android Platform Tools。", code="adb_missing")
        rows = command(self.adb, "devices", "-l").decode(errors="replace").splitlines()[1:]
        entries = [fields for fields in map(str.split, rows) if len(fields) >= 2]
        devices = [
            fields[0] for fields in entries
            if len(fields) > 2 and fields[1] == "device"
            and any(field.startswith(("usb:", "transport_id:")) for field in fields[2:])
            and not fields[0].startswith("emulator-")
            and ":" not in fields[0] and not fields[0].endswith("._adb-tls-connect._tcp")
        ]
        if serial is None:
            if len(devices) != 1:
                states = ", ".join(fields[1] for fields in entries) or "无设备"
                raise Stop(f"需要一台已授权的 USB 真机。当前 ADB 状态：{states}。多台真机请用 --serial 指定。",
                           code="adb_device_unavailable")
            serial = devices[0]
        if serial not in devices:
            raise Stop("未找到指定的已授权手机。", code="adb_device_unavailable")
        self.serial = serial

    def call(self, *args, timeout=20):
        operation = args[1] if args[0] == "shell" else args[0]
        try:
            return command(self.adb, "-s", self.serial, *args, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Stop(f"ADB {operation} 等待超过 {timeout} 秒。", code="adb_timeout") from None
        except Stop as exc:
            message = str(exc).replace(self.serial, "<device>")
            unavailable = re.search(r"no devices|device.*(?:offline|unauthorized|not found|disconnected)|transport.*closed",
                                    message, re.IGNORECASE)
            code = "adb_device_unavailable" if unavailable else "adb_command_failed"
            raise Stop(f"ADB {operation}: {message}", code=code) from None

    def component(self):
        out = self.call("shell", "dumpsys", "activity", "activities").decode(errors="replace")
        match = re.search(r"(?:topResumedActivity=|mResumedActivity:).*?\s([\w.]+)/([\w.$]+)", out)
        if not match:
            return None, None
        package, activity = match.groups()
        return package, package + activity if activity.startswith(".") else activity

    def frame(self, *, allow_landscape=False, diagnostic=False, timeout=20):
        sizes = {(2400, 1080), (1080, 2400)} if allow_landscape else {(2400, 1080)}
        attempts = 1 if diagnostic else 2
        for attempt in range(attempts):
            data = self.call("exec-out", "screencap", "-p", timeout=timeout)
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
            if image is not None:
                if not diagnostic and image.shape[:2] not in sizes:
                    raise Stop("请保持手机 1080×2400 竖屏。", code="screenshot_size_mismatch")
                return image
            if attempt + 1 < attempts:
                time.sleep(0.3)
        if not data:
            raise Stop("手机截图不可用，请确认已解锁。", code="screenshot_empty")
        raise Stop("手机截图无法解码。", code="screenshot_decode_failed")

    def tap(self, box, *, activity=None):
        package, foreground = self.component()
        if package != MEITUAN or (activity is not None and foreground != activity):
            raise Stop(f"点击前页面已切换（{package}/{foreground}）。", code="foreground_changed_before_tap")
        self.call("shell", "input", "tap", *map(str, center(box)))

    def scroll(self, down, *, wide=False):
        if self.component() != (MEITUAN, GAME):
            raise Stop("滚动前未确认游戏在前台。")
        if wide:
            top, bottom = 1510, 2190
        else:
            top, bottom = (1710, 2090) if down else (1630, 2010)
        start, end = (bottom, top) if down else (top, bottom)
        self.call("shell", "input", "swipe", "475", str(start), "475", str(end), "900")
        time.sleep(1.0)

    def back(self):
        self.call("shell", "input", "keyevent", "KEYCODE_BACK")

    def return_to_game(self, *, main=False):
        self.call("shell", "am", "start", "-a", "android.intent.action.MAIN", "-c",
                  "android.intent.category.LAUNCHER", "-f", "0x34000000" if main else "0x10200000", "-n", MAIN)


class Runner:
    def __init__(self):
        self.phone = None
        self.run = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.run.mkdir(parents=True)
        self.evidence_dir = self.run / "screenshots"
        self.evidence_dir.mkdir()
        self.sequence = 0
        self.task_key = None
        self.phase = "startup"
        self.round_info = None
        self.last_remaining = None
        self.progress_cache = None
        self.recent_frames = {}
        self.last_component = None
        self.last_heartbeat = time.monotonic()
        self.final_rewards = 0
        self.capacity_recoveries = 0
        self.blocked = False
        self.templates = {
            p.stem: cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
            for p in (ROOT / "templates").glob("*.png")
        }

    def log(self, event, **fields):
        fields.setdefault("task", self.task_key)
        with (self.run / "events.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "event": event,
                                   "phase": self.phase, **fields},
                                  ensure_ascii=False) + "\n")

    def stage(self, phase):
        if self.phase != phase:
            previous = self.phase
            self.phase = phase
            self.log("phase_changed", previous=previous)

    def remember(self, label, image):
        captured_at = datetime.now().isoformat(timespec="milliseconds")
        self.recent_frames[label] = (image, captured_at, self.phase)

    def evidence(self, label, image=None, *, captured_at=None, capture_phase=None):
        if image is None and self.phone is None:
            self.log("screenshot_unavailable", label=label, reason="ADB 未连接到已授权手机。")
            return
        self.sequence += 1
        name = f"{self.sequence:04d}-{self.task_key or 'session'}-{label}.png"
        try:
            if image is None:
                image = self.phone.frame(diagnostic=True, timeout=3)
                captured_at = datetime.now().isoformat(timespec="milliseconds")
            save(self.evidence_dir / name, image)
            self.log("screenshot", label=label, file=f"screenshots/{name}", captured_at=captured_at,
                     capture_phase=capture_phase or self.phase, width=image.shape[1], height=image.shape[0])
        except (Stop, OSError, subprocess.TimeoutExpired, cv2.error) as exc:
            self.log("screenshot_unavailable", label=label, code=getattr(exc, "code", None), reason=str(exc))

    def record_stop(self, exc, code, *, unexpected=False):
        self.log("stopped", code=code, reason=str(exc) or type(exc).__name__, exception=type(exc).__name__,
                 round=self.round_info, last_remaining=self.last_remaining, last_foreground=self.last_component)
        if unexpected:
            self.log("exception_traceback", traceback=traceback.format_exc())
        for label, (image, captured_at, capture_phase) in self.recent_frames.items():
            self.evidence(label, image, captured_at=captured_at, capture_phase=capture_phase)
        self.evidence("interrupted")
        self.log("diagnostics_finished")

    def component(self):
        component = self.phone.component()
        if component[0] and component != self.last_component:
            self.last_component = component
            self.log("foreground_changed", package=component[0], activity=component[1])
            self.evidence("foreground")
        now = time.monotonic()
        if now - self.last_heartbeat >= 8:
            self.log("heartbeat", package=component[0], activity=component[1])
            self.last_heartbeat = now
        return component

    def match(self, image, name, region, threshold=0.91, *, first=False):
        template = self.templates[name]
        box = cv2.cvtColor(crop(image, region), cv2.COLOR_BGR2GRAY)
        height, width = template.shape
        if min(box.shape) == 0 or height > box.shape[0] or width > box.shape[1]:
            return None
        scores = cv2.matchTemplate(box, template, cv2.TM_CCOEFF_NORMED)
        if first:
            rows = np.flatnonzero(scores.max(axis=1) >= threshold)
            if not len(rows):
                return None
            start = int(rows[0])
            scores = scores[start:start + 12]
        else:
            start = 0
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        y += start
        if score >= threshold:
            x, y = x + region[0], y + region[1]
            return (x, y, x + width, y + height)
        return None

    def panel(self):
        deadline = time.monotonic() + 20
        next_open = 0.0
        open_attempts = 0
        merge_batches = 0
        while time.monotonic() < deadline:
            if self.component() == (MEITUAN, GAME):
                image = self.phone.frame()
                self.remember("last-panel-check", image)
                if self.match(image, "capacity", (170, 1120, 919, 1270), 0.87):
                    if merge_batches >= 2:
                        raise Stop("已执行两批一键合成，游戏仍提示放置区角色已达上限。", code="capacity_unresolved")
                    self.evidence("capacity-full", image)
                    self.merge_for_capacity(image)
                    merge_batches += 1
                    next_open = 0.0
                    open_attempts = 0
                    deadline = time.monotonic() + 20
                    continue
                # During the entrance animation the title can be dim while the buttons are readable.
                if self.match(image, "reward", (220, 390, 860, 620), 0.84):
                    later = self.match(image, "later", (90, 1570, 490, 1800), 0.81)
                    final = self.match(image, "final", (350, 1570, 730, 1800))
                    if not (later or final):
                        time.sleep(0.45)
                        continue
                    is_final = later is None and final is not None
                    self.evidence("final-reward" if is_final else "reward", image)
                    self.phone.tap(later or final, activity=GAME)
                    if is_final:
                        self.final_rewards += 1
                    self.log("reward_dismissed", final=is_final)
                elif self.match(image, "offline", (272, 385, 815, 565)):
                    close = self.match(image, "offline_close", (303, 1800, 772, 1969))
                    if not close:
                        raise Stop("离线收益浮层遮住任务入口，未识别跳过按钮。")
                    self.phone.tap(close)
                elif self.match(image, "home_bonus_double", (180, 565, 872, 815)):
                    close = self.match(image, "home_bonus_skip", (345, 1790, 750, 1925))
                    if close:
                        self.phone.tap(close, activity=GAME)
                        self.log("home_bonus_skipped")
                elif self.match(image, "panel", (365, 685, 716, 834)):
                    if panel_header_visible(image):
                        return image
                elif open_attempts < 3 and time.monotonic() >= next_open:
                    entry = self.match(image, "task_entry", (750, 2060, 905, 2260), 0.86)
                    if entry:
                        x = center(entry)[0]
                        y = entry[1] - 34
                        self.phone.tap((x, y, x, y), activity=GAME)
                        self.log("task_panel_tap", point=(x, y))
                        open_attempts += 1
                        next_open = time.monotonic() + 4
            time.sleep(0.4)
        raise Stop("未确认「领现金 → 每日任务」。", code="task_panel_unavailable")

    def merge_for_capacity(self, image):
        if self.match(image, "panel", (365, 685, 716, 834)):
            close = self.match(image, "panel_close", (950, 676, 1060, 800))
            if not close:
                raise Stop("放置区已满，但每日任务面板关闭按钮未确认。")
            self.phone.tap(close, activity=GAME)
            time.sleep(0.7)
        print("放置区已满，按 5.5 秒间隔执行 10 次一键合成。", flush=True)
        for step in range(10):
            if self.component() != (MEITUAN, GAME):
                raise Stop("一键合成期间已离开领现金游戏。")
            image = self.phone.frame()
            entry = self.match(image, "task_entry", (750, 2060, 905, 2260), 0.86)
            button = self.match(image, "merge", (915, 1680, 1062, 1850), 0.85)
            if not (entry and button):
                raise Stop("未确认游戏首页的「一键合成」按钮。")
            self.phone.tap(button, activity=GAME)
            self.log("capacity_merge", step=step + 1)
            time.sleep(5.5)
        self.capacity_recoveries += 1
        self.evidence("capacity-after")

    def row(self, image, task, *, top=LIST[1]):
        if not panel_header_visible(image):
            return None
        while top < 2340:
            title = self.match(image, task.title, (227, top, 610, 2345), first=True)
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

    def find(self, task, image, *, wide=True):
        for down in (False, True):
            still = 0
            direction = "down" if down else "up"
            for step in range(37):
                row = self.row(image, task)
                if row:
                    time.sleep(0.8)
                    image = self.panel()
                    stable = self.row(image, task)
                    if stable and abs(stable[0][1] - row[0][1]) <= 5:
                        while stable:
                            try:
                                self.remaining(image, task, stable[0])
                                return image, stable
                            except DifferentTotal as exc:
                                self.log("task_candidate_skipped", reason=str(exc), title_box=stable[0])
                                stable = self.row(image, task, top=stable[0][1] + 68)
                    else:
                        continue
                if still >= 2 or step == 36:
                    break
                old = crop(image, LIST)
                self.phone.scroll(down, wide=wide)
                image = self.panel()
                self.remember(f"scan-{direction}", image)
                current = crop(image, LIST)
                difference = cv2.norm(old, current, cv2.NORM_L1) / current.size
                still = still + 1 if difference < 1.55 else 0
                self.log("task_scan_scroll", direction=direction, step=step + 1, difference=round(difference, 2),
                         stable_scrolls=still, wide=wide)
                if wide and still == 0 and not list_frames_overlap(old, current, down):
                    self.log("task_scan_narrow_retry", direction=direction, step=step + 1)
                    return self.find(task, image, wide=False)
        self.evidence("task-scan-end", image)
        return image, None

    def ocr(self, image, filename):
        path = self.run / filename
        save(path, image)
        return command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                       str(ROOT / "read-progress.ps1"), "-Image", str(path)).decode("utf-8", errors="replace").strip()

    def remaining(self, image, task, title):
        y = title[1]
        gray = cv2.cvtColor(crop(image, (225, y - 3, 782, y + 59)), cv2.COLOR_BGR2GRAY)
        key = (task.key, task.total, gray.shape, gray.tobytes())
        if self.progress_cache is not None and key == self.progress_cache[0]:
            _, remaining, ocr_ms = self.progress_cache
            self.log("progress_ocr_reused", remaining=remaining, previous_ocr_ms=ocr_ms)
            return remaining
        started = time.monotonic()
        _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)
        other_total = None
        readings = {}
        for variant, style in (("gray", gray), ("binary", binary)):
            enlarged = cv2.resize(style, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            padded = cv2.copyMakeBorder(enlarged, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
            filename = f"progress-{task.key}-{variant}.png"
            raw = self.ocr(padded, filename)
            readings[filename] = raw
            value = re.sub(r"\s+", "", raw).replace("／", "/")
            if task.total is None:
                # The row title is already verified visually. Read only its trailing count.
                match = re.search(r"(?<!\d)(\d{1,2})次[)）]?$", value)
                if match and int(match[1]) <= 30:
                    remaining = int(match[1])
                    break
            else:
                match = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", value)
                if match:
                    done, total = map(int, match.groups())
                    if total == task.total and done <= total:
                        remaining = total - done
                        break
                    if 0 <= done <= total <= 30:
                        other_total = total
        else:
            if other_total is not None and other_total != task.total:
                raise DifferentTotal(f"同名任务总次数为 {other_total}，期望 {task.total}。")
            self.remember("progress-unreadable", image)
            self.log("progress_ocr_failed", title_box=title, readings=readings)
            raise Stop(f"无法确认「{task.name}」进度，识别结果 {raw!r}。", code="progress_unreadable")
        ocr_ms = round((time.monotonic() - started) * 1000)
        self.progress_cache = (key, remaining, ocr_ms)
        self.log("progress_ocr_read", remaining=remaining, ocr_ms=ocr_ms)
        return remaining

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
        started = time.monotonic()
        deadline = started + 13
        probes = 0
        while time.monotonic() < deadline:
            package, activity = self.component()
            if package == MEITUAN:
                if task.key == "promo" and activity == SUBGAME:
                    self.log("promo_subgame", seconds=12)
                    time.sleep(12)
                    return self.leave_subgame()
                image = self.phone.frame()
                probes += 1
                if probes == 1:
                    self.remember("after-task-tap-first", image)
                self.remember("after-task-tap-latest", image)
                if task.key == "goods" and self.goods_card_button(image):
                    self.evidence("goods-card", image)
                    return self.browse_goods_card(image)
                button = self.ad_button(image)
                if button:
                    self.evidence("ad-prompt", image)
                    self.phone.tap(button[0])
                    self.log("ad_opened", task=task.key, seconds=button[1])
                    return self.browse_landing(button[1])
                if activity == FULL_AD:
                    return self.full_ad()
                if activity == TITANS_WEB:
                    return self.browse_internal(activity, 10 if task.key == "promo" else 5)
                if task.key == "promo" and self.is_promo_landing(activity, image):
                    return self.browse_internal(activity, 10)
                if (task.key == "goods" and activity == MRN
                    and self.match(image, "goods_landing", (191, 115, 902, 278))):
                    return self.browse_internal(activity, 5)
                if (task.key == "goods" and activity == MRN
                    and self.match(image, "goods_refund", (170, 110, 902, 260), 0.88)):
                    time.sleep(7)
                    if self.component() == (MEITUAN, activity):
                        close = self.match(self.phone.frame(), "goods_refund_close", (470, 1730, 609, 1860), 0.87)
                        if close:
                            self.phone.tap(close)
                            time.sleep(0.5)
                        self.phone.back()
                    return self.panel()
            time.sleep(0.5)
        package, activity = self.component()
        self.log("task_open_timeout", package=package, activity=activity, probes=probes,
                 elapsed=round(time.monotonic() - started, 2))
        if (package, activity) == (MEITUAN, GAME):
            image = self.phone.frame()
            self.remember("task-open-timeout", image)
            if self.match(image, "panel", (365, 685, 716, 834)):
                final_before_rescan = self.final_rewards
                image = self.panel()
                self.evidence("panel-after-task-tap", image)
                self.stage("rescan_after_tap")
                self.log("task_panel_rescan", target_visible=bool(self.row(image, task)))
                image, row = self.find(task, image)
                if row is None:
                    if self.final_rewards > final_before_rescan:
                        self.log("final_reward_during_rescan")
                        return image
                    raise Stop(f"点击后重新扫描，仍未找到「{task.name}」。", code="task_missing_after_tap")
                self.blocked = True
                self.log("task_still_on_panel", title_box=row[0], go_visible=bool(row[1]))
                return image
        raise Stop(f"「{task.name}」未识别到广告按钮或已验证的落地页。", code="task_open_unrecognized")

    def is_promo_landing(self, activity, image):
        if activity == MRN:
            return bool(self.match(image, "merchant", (555, 2210, 820, 2330))
                        or self.match(image, "promo_special_group", (68, 94, 304, 208)))
        if activity == TRAVEL_DETAIL:
            return bool(self.match(image, "travel_detail_tabs", (18, 1440, 840, 1810)))
        return activity == WEB

    def goods_card_button(self, image):
        layouts = (
            ((108, 1190, 485, 1350), (878, 585, 1007, 712), (359, 1520, 768, 1712)),
            ((100, 1285, 510, 1450), (879, 477, 1008, 601), (358, 1660, 776, 1818)),
        )
        for title, close, button in layouts:
            if self.match(image, "goods_card", title) or self.goods_card_close(image, close, 0.88):
                if result := self.match(image, "goods_card_button", button):
                    return result
        return None

    def goods_card_close(self, image, region, threshold=0.91):
        return (self.match(image, "goods_card_close", region, threshold)
                or self.match(image, "goods_card_close_icon", region, 0.94))

    def goods_card_landing_status(self, activity):
        if activity in {WEB, TITANS_WEB, DEAL_DETAIL, MRN}:
            return "ready"
        if activity == MRNX:
            image = self.phone.frame()
            if self.match(image, "goods_deal_unavailable", (320, 1150, 760, 1450), 0.93):
                return "unavailable"
            if (self.match(image, "goods_deal_details", (18, 850, 320, 1800), 0.90)
                and self.match(image, "goods_deal_cart", (355, 2188, 681, 2335), 0.90)):
                return "ready"
        if activity == MRN_STANDARD:
            image = self.phone.frame()
            if (self.match(image, "goods_store_tabs", (18, 1150, 760, 2050), 0.90)
                and (self.match(image, "goods_store_order", (362, 1730, 720, 2180), 0.90)
                     or self.match(image, "goods_store_directions", (15, 1020, 285, 1340), 0.91))):
                return "ready"
            if (self.match(image, "goods_store_recommendations", (335, 700, 810, 1070), 0.92)
                and self.match(image, "goods_store_menu", (25, 980, 320, 1370), 0.92)):
                return "ready"
        return None

    def finish_goods_card_landing(self, activity, status):
        if status == "unavailable":
            self.blocked = True
            self.evidence("goods-deal-unavailable")
            self.log("goods_deal_unavailable", activity=activity)
        else:
            self.log("goods_card_landing", activity=activity, seconds=7)
            time.sleep(7)
        if self.component() == (MEITUAN, activity):
            self.phone.back()
            time.sleep(1.2)
        if self.component() == (MEITUAN, GAME):
            current = self.phone.frame()
            if self.goods_card_button(current):
                close = (self.goods_card_close(current, (878, 585, 1007, 712))
                         or self.goods_card_close(current, (879, 477, 1008, 601)))
                if not close:
                    raise Stop("未确认浏览卡片关闭按钮。")
                self.phone.tap(close, activity=GAME)
        return self.panel()

    def browse_goods_card(self, image):
        self.stage("goods_card")
        button = self.goods_card_button(image)
        if not button:
            raise Stop("未确认惊喜特价卡片的「浏览5s领奖励」。")
        time.sleep(0.7)
        if self.component() != (MEITUAN, GAME):
            raise Stop("惊喜特价卡片在点击前已离开游戏。")
        button = self.goods_card_button(self.phone.frame())
        if not button:
            raise Stop("惊喜特价卡片在点击前已变化。")
        self.phone.tap(button, activity=GAME)
        deadline = time.monotonic() + 20
        retry_at = time.monotonic() + 4
        retries = 0
        while time.monotonic() < deadline:
            package, activity = self.component()
            if package == MEITUAN and (status := self.goods_card_landing_status(activity)):
                return self.finish_goods_card_landing(activity, status)
            if is_ad_landing((package, activity)):
                return self.browse_landing(5)
            if (package, activity) == (MEITUAN, GAME) and retries < 2 and time.monotonic() >= retry_at:
                button = self.goods_card_button(self.phone.frame())
                if button:
                    self.phone.tap(button, activity=GAME)
                    retries += 1
                    retry_at = time.monotonic() + 4
                    self.log("goods_card_retry", attempt=retries)
            time.sleep(0.45)
        raise Stop("打开好物浏览卡片后未识别落地页。", code="goods_landing_unrecognized")

    def full_ad(self):
        self.stage("full_ad")
        deadline = time.monotonic() + 50
        button_missing_since = None
        while time.monotonic() < deadline:
            if self.component() != (MEITUAN, FULL_AD):
                break
            image = self.phone.frame()
            self.remember("last-full-ad-check", image)
            if self.close_download_modal(image):
                time.sleep(0.7)
                image = self.phone.frame()
            if self.full_ad_done(image):
                if self.phone.component() != (MEITUAN, FULL_AD):
                    break
                self.log("full_ad_confirmed")
                self.phone.back()
                time.sleep(1.3)
                return self.panel()
            replay = self.match(image, "replay", (390, 1440, 690, 1590), 0.83)
            instruction = self.match(image, "full_instruction", (90, 159, 472, 255), 0.80)
            if self.match(image, "full_download", (416, 1315, 667, 1460), 0.90):
                self.blocked = True
                self.log("full_ad_download_skipped")
                self.phone.back()
                time.sleep(1.3)
                return self.panel()
            if instruction and self.match(image, "full_banner", (111, 1710, 974, 1850), 0.85):
                footer = self.match(image, "full_footer_open", (419, 2125, 671, 2245), 0.88)
                if footer:
                    self.phone.tap(footer, activity=FULL_AD)
                    return self.browse_landing(10, from_full=True)
            if replay and instruction:
                replay_top = replay[1]
                region = (416, replay_top - 161, 653, replay_top - 45)
                button = next((match for name in ("full_open", "full_click", "full_click_alt", "full_details")
                               if (match := self.match(image, name, region, 0.88))), None)
                if not button:
                    region = (384, replay_top - 141, 697, replay_top - 61)
                    pixels = crop(image, region)
                    blue, green, red = cv2.split(pixels)
                    if np.mean((red > 190) & (green > 155) & (blue < 140)) > 0.68:
                        title = re.sub(r"\s+", "", self.ocr(pixels, "full-ad-button.png"))
                        if title in {"立即点击", "立即打开", "立即体验", "查看详情"}:
                            button = region
                if not button:
                    now = time.monotonic()
                    if button_missing_since is None:
                        button_missing_since = now
                        self.log("full_ad_wait_for_button")
                    if now - button_missing_since < 5 and now < deadline:
                        time.sleep(0.5)
                        continue
                    raise Stop("全屏广告要求打开落地页，但未确认入口按钮。", code="full_ad_button_unrecognized")
                self.phone.tap(button, activity=FULL_AD)
                return self.browse_landing(10, from_full=True)
            button_missing_since = None
            time.sleep(0.8)
        raise Stop("未确认全屏广告已播放结束。", code="full_ad_unconfirmed")

    def full_ad_done(self, image):
        region = (95, 156, 485, 254)
        return bool(self.match(image, "full_done", region, 0.81)
                    or self.match(image, "full_done_dim", region, 0.92))

    def close_download_modal(self, image):
        if not self.match(image, "download_modal", (377, 1355, 706, 1525), 0.90):
            return False
        close = self.match(image, "download_modal_close", (840, 815, 976, 950), 0.89)
        if not close:
            self.remember("download-dialog", image)
            raise Stop("出现下载浮层，但未确认关闭按钮。", code="download_close_unrecognized")
        self.evidence("download-dialog", image)
        self.phone.tap(close, activity=FULL_AD)
        self.log("download_modal_closed")
        return True

    def leave_subgame(self):
        for _ in range(3):
            component = self.component()
            if component == (MEITUAN, GAME):
                return self.panel()
            if component != (MEITUAN, SUBGAME):
                break
            image = self.phone.frame(allow_landscape=True)
            width = image.shape[1]
            if width == 2400:
                button = self.match(image, "subgame_exit", (width - 160, 36, width - 35, 165), 0.86)
                if not button:
                    break
                self.phone.tap(button)
                time.sleep(1.1)
                continue
            if self.match(image, "update_prompt", (400, 1002, 685, 1162)):
                button = self.match(image, "update_cancel", (186, 1286, 509, 1396))
            else:
                button = self.match(image, "subgame_exit", (920, 36, 1045, 165), 0.86)
            if not button:
                break
            self.phone.tap(button)
            time.sleep(1.1)
        component = self.component()
        if component == (MEITUAN, SUBGAME):
            self.blocked = True
            self.phone.return_to_game(main=True)
            self.log("subgame_return_to_main")
            time.sleep(12)
            self.reopen_game()
        elif component == MAIN_COMPONENT:
            self.blocked = True
            self.log("subgame_returned_directly_to_main")
            self.reopen_game()
        return self.panel()

    def reopen_game(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.component() == MAIN_COMPONENT:
                image = self.phone.frame()
                for name, region in (
                    ("profile_game", (280, 1750, 558, 2010)),
                    ("home_game", (229, 1195, 436, 1290)),
                ):
                    entry = self.match(image, name, region)
                    if entry:
                        x, y = center(entry)
                        self.phone.tap((x, y - 60, x, y - 60))
                        self.log("subgame_reopen", entry=name)
                        return
            time.sleep(0.5)
        raise Stop("退出子游戏后未在美团首页或「我的」找到领现金入口。")

    def browse_landing(self, seconds, *, from_full=False):
        self.stage("open_landing")
        started = time.monotonic()
        deadline = started + 12
        while time.monotonic() < deadline:
            package, activity = self.component()
            # The full-ad activity can remain visible while its landing starts.
            if (from_full and (package, activity) == (MEITUAN, FULL_AD)
                and time.monotonic() - started >= 2):
                image = self.phone.frame()
                if self.close_download_modal(image) or self.full_ad_done(image):
                    return self.finish_ad_return(True)
            if not from_full and (package, activity) == (MEITUAN, FULL_AD):
                return self.full_ad()
            if not from_full and (package, activity) == (MEITUAN, WEB):
                return self.browse_internal(activity, seconds)
            if package == MEITUAN and activity in {WEB, TITANS_WEB, AD_WEB, AD_SHOP}:
                time.sleep(seconds + 2)
                return self.finish_ad_return(from_full)
            if (package, activity) == APP_LOCK:
                return self.return_from_app_lock(seconds, from_full=from_full)
            if is_ad_landing((package, activity)):
                self.log("landing", package=package, activity=activity)
                time.sleep(seconds + 2)
                current = self.component()
                deadline = time.monotonic() + 5
                while (current[0] is None or (from_full and current == CLOUD_HANDOFF)) and time.monotonic() < deadline:
                    time.sleep(0.5)
                    current = self.component()
                if current[0] == MEITUAN:
                    return self.finish_ad_return(from_full)
                if not is_ad_landing(current):
                    raise Stop("广告停留期间页面发生切换。", code="landing_changed")
                self.phone.return_to_game()
                time.sleep(1.3)
                return self.finish_ad_return(from_full)
            # These transitions do not start the dwell timer.
            handoff = (package, activity) == DOUYIN_HANDOFF or (from_full and (package, activity) == CLOUD_HANDOFF)
            if package not in (None, MEITUAN) and not handoff:
                raise Stop(f"广告跳转到尚未验证的应用 {package}。", code="landing_app_unrecognized")
            time.sleep(0.5)
        raise Stop("广告打开后未识别落地页，尚未确认浏览计时。", code="landing_unrecognized")

    def return_from_app_lock(self, seconds=0, *, from_full=False):
        self.log("app_lock_return")
        self.blocked = True
        self.phone.return_to_game()
        time.sleep(1.3)
        package, activity = self.component()
        if is_ad_landing((package, activity)):
            self.log("app_lock_landing", package=package, activity=activity)
            if seconds:
                time.sleep(seconds + 2)
            package, activity = self.component()
            if is_ad_landing((package, activity)):
                self.phone.return_to_game()
                time.sleep(1.3)
                package, activity = self.component()
        if package == MEITUAN:
            image = self.phone.frame()
            if self.ad_button(image):
                close = self.match(image, "ad_close", (479, 1680, 603, 1905), 0.85)
                if close:
                    self.phone.tap(close, activity=activity)
        return self.finish_ad_return(from_full)

    def finish_ad_return(self, from_full):
        self.stage("return_to_game")
        component = self.component()
        if component in WECHAT_AD_WEB_VIEWS:
            for _ in range(3):
                if component not in WECHAT_AD_WEB_VIEWS:
                    break
                if self.phone.component() in WECHAT_AD_WEB_VIEWS:
                    self.phone.back()
                    self.log("wechat_ad_web_back", activity=component[1])
                    time.sleep(1.3)
                component = self.component()
        if component[0] == "com.xiaomi.market" and component[1] in {
            "com.xiaomi.market.ui.detail.AppDetailMiniCardActivity",
            "com.xiaomi.market.ui.detail.AppDetailCardActivity",
        }:
            self.phone.back()
            time.sleep(0.6)
            self.phone.return_to_game()
            time.sleep(1.3)
            component = self.component()
        if component == (MEITUAN, AD_WEB):
            close = self.match(self.phone.frame(), "ad_web_close", (145, 112, 265, 229), 0.89)
            if close is None:
                raise Stop("未确认广告网页顶部的关闭按钮。")
            self.phone.tap(close, activity=AD_WEB)
            self.log("ad_web_closed")
            time.sleep(1.3)
            component = self.component()
        if component == (MEITUAN, AD_SHOP):
            image = self.phone.frame()
            close = self.match(image, "ad_shop_close", (960, 109, 1067, 228))
            if not close:
                raise Stop("未确认原生广告页的关闭按钮。")
            self.phone.tap(close, activity=AD_SHOP)
            self.log("ad_shop_closed")
            time.sleep(1.3)
            component = self.component()
        if is_ad_landing(component):
            self.log("landing_redirected_again")
            self.phone.return_to_game()
            time.sleep(1.5)
            component = self.component()
            if component in {(MEITUAN, AD_WEB), (MEITUAN, AD_SHOP)}:
                self.phone.back()
                time.sleep(1.3)
                component = self.component()
        if component in {(MEITUAN, WEB), (MEITUAN, TITANS_WEB)}:
            for _ in range(2):
                if self.phone.component() != component:
                    break
                self.phone.back()
                self.log("ad_web_back", activity=component[1])
                time.sleep(1.3)
            component = self.component()
        if component == (MEITUAN, MRN_STANDARD):
            image = self.phone.frame()
            if self.ad_button(image):
                close = self.match(image, "ad_close", (479, 1680, 603, 1905), 0.85)
                if close:
                    self.phone.tap(close, activity=MRN_STANDARD)
                    self.blocked = True
                    self.log("residual_ad_closed")
                    time.sleep(1.3)
                    component = self.component()
        if from_full:
            deadline = time.monotonic() + 8
            while component == (MEITUAN, FULL_AD):
                image = self.phone.frame()
                self.remember("last-full-ad-check", image)
                if self.full_ad_done(image) and self.phone.component() == (MEITUAN, FULL_AD):
                    self.phone.back()
                    self.log("full_ad_confirmed")
                    time.sleep(1.3)
                    break
                if time.monotonic() >= deadline:
                    raise Stop("广告落地页返回后未显示「已完成，返回领奖励」。", code="full_ad_return_unconfirmed")
                time.sleep(0.5)
                component = self.component()
        return self.panel()

    def browse_internal(self, activity, seconds):
        self.stage("browse_internal")
        self.log("landing", package=MEITUAN, activity=activity, seconds=seconds)
        time.sleep(seconds + 2)
        for _ in range(2):
            if self.component() != (MEITUAN, activity):
                break
            self.phone.back()
            time.sleep(1.2)
        return self.panel()

    def settlement(self, image, task, left, final_before):
        self.stage("settlement")
        deadline = time.monotonic() + 10
        after = None
        claimed = False
        while True:
            self.remember("last-settlement-check", image)
            row = self.row(image, task)
            if row:
                if not claimed:
                    reward_result = self.collect_ready(image, task, row)
                    if reward_result is not None:
                        claimed = True
                        image = reward_result
                        continue
                try:
                    after = self.remaining(image, task, row[0])
                except DifferentTotal:
                    row = None
                    deadline = time.monotonic()
                except Stop as exc:
                    if exc.code != "progress_unreadable" or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.55)
                    image = self.panel()
                    continue
                if row and after != left:
                    return image, row, after
            final_seen = left == 1 and self.final_rewards > final_before
            if time.monotonic() >= deadline or (not row and final_seen):
                if row:
                    return image, row, after
                image, row = self.find(task, image)
                if row:
                    return image, row, self.remaining(image, task, row[0])
                if left == 1 and self.final_rewards > final_before:
                    return image, None, 0
                raise Stop(f"浏览后未找到「{task.name}」，无法核对结算。", code="settlement_target_missing")
            time.sleep(0.55)
            image = self.panel()

    def claim_ready(self, image, task, row):
        if task.key != "goods" or row[1]:
            return False
        y = row[0][1]
        button = self.match(image, "claim", (805, max(LIST[1], y - 24), 1006, min(2380, y + 115)))
        if not button:
            return False
        self.remember("before-task-claim", image)
        self.log("task_claim_intent", point=center(button))
        self.phone.tap(button, activity=GAME)
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

    def finish(self, task, limit, *, resume_final_before=None):
        self.task_key = task.key
        self.last_remaining = None
        self.round_info = None
        self.recent_frames.clear()
        self.stage("locate_task")
        image, row = self.find(task, self.panel())
        if row is None:
            if resume_final_before is not None and self.final_rewards > resume_final_before:
                self.last_remaining = 0
                self.log("task_finished", task=task.key, remaining=0)
                print(f"{task.name}：最终奖励已结算。", flush=True)
                return
            self.log("task_not_listed", task=task.key)
            print(f"当前列表未显示「{task.name}」，跳过。", flush=True)
            return
        final_before = self.final_rewards
        claimed_image = self.collect_ready(image, task, row)
        if claimed_image is not None:
            image, row = self.find(task, claimed_image)
            if row is None:
                if self.final_rewards > final_before:
                    self.last_remaining = 0
                    self.log("task_finished", task=task.key, remaining=0)
                    print(f"{task.name}：最终奖励已结算。", flush=True)
                    return
                raise Stop("领取好物奖励后未确认任务状态。", code="claim_state_unconfirmed")
        left = self.remaining(image, task, row[0])
        self.last_remaining = left
        print(f"{task.name}：剩余 {left} 次。", flush=True)
        self.log("task_started", task=task.key, remaining=left)
        self.evidence("task-start", image)
        rounds = min(left, limit) if limit else left
        retries = 0
        while rounds > 0:
            self.recent_frames.clear()
            self.round_info = {"remaining_before": left, "attempt": retries + 1}
            self.stage("prepare_task_tap")
            current = self.panel()
            fresh = self.row(current, task, top=max(LIST[1], row[0][1] - 8))
            if fresh is None or abs(fresh[0][1] - row[0][1]) > 8:
                current, fresh = self.find(task, current)
            if fresh and fresh[1] is None:
                raise Stop(f"「{task.name}」仍有剩余，但未看到「去完成」。", code="task_go_missing")
            if not fresh:
                raise Stop("点击前任务行已变化。", code="task_changed_before_tap")
            if row[1] is None or abs(fresh[1][1] - row[1][1]) > 12:
                if self.remaining(current, task, fresh[0]) != left:
                    raise Stop("点击前任务进度已变化。", code="progress_changed_before_tap")
            for _ in range(5):
                time.sleep(0.6)
                stable = self.phone.frame()
                self.remember("last-stability-check", stable)
                checked = self.row(stable, task, top=max(LIST[1], fresh[0][1] - 8))
                if not checked or checked[1] is None:
                    continue
                if abs(checked[1][1] - fresh[1][1]) <= 5:
                    break
            else:
                raise Stop("列表仍在移动，未点击任务。", code="task_row_unstable")
            y = checked[0][1]
            row_file = f"row-{task.key}-{left}-{retries}.png"
            save(self.run / row_file, crop(stable, (53, y - 23, 1038, y + 100)))
            self.recent_frames.pop("last-stability-check", None)
            self.remember("before-task-tap", stable)
            self.round_info.update(point=center(checked[1]), title_box=checked[0], button_box=checked[1],
                                   row_file=row_file, tap_acknowledged=False)
            self.log("task_tap_intent", **self.round_info)
            self.phone.tap(checked[1], activity=GAME)
            self.round_info["tap_acknowledged"] = True
            self.log("task_tap", task=task.key, point=center(checked[1]))
            final_before = self.final_rewards
            self.blocked = False
            self.stage("wait_for_task")
            image, row, after = self.settlement(self.open_round(task), task, left, final_before)
            self.round_info["remaining_observed"] = after
            if after == left and self.blocked:
                if not row or not row[1]:
                    raise Stop("进度未变化，且重新确认后没有可重试的「去完成」按钮。", code="retry_button_missing")
                if retries >= 3:
                    raise Stop("同一轮已重试 3 次，剩余次数仍未减少。", code="task_retry_exhausted")
                retries += 1
                self.log("blocked_retry", task=task.key, remaining=left, retry=retries)
                self.evidence("before-round-retry", image)
                continue
            if after != left - 1:
                raise Stop(f"「{task.name}」剩余次数未按预期变化（{left} → {after}）。", code="settlement_progress_mismatch")
            self.last_remaining = after
            self.log("round_confirmed", task=task.key, remaining=after)
            self.evidence("round-confirmed", image)
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
    parser.add_argument("--recover-landing", action="store_true", help="从本程序打开的已知广告落地页返回")
    args = parser.parse_args()
    if not 0 <= args.limit <= 30:
        parser.error("--limit must be between 0 and 30")
    if args.resume_ad and (not args.execute or args.task == "all"):
        parser.error("--resume-ad requires --execute and a specific --task")
    if args.recover_landing and (not args.execute or args.resume_ad):
        parser.error("--recover-landing requires --execute and cannot be combined with --resume-ad")
    runner = None
    try:
        with (ROOT / "session.lock").open("a+b") as lock:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            runner = Runner()
            runner.task_key = None if args.task == "all" else args.task
            print(f"运行记录：{runner.run}", flush=True)
            runner.log("run_started", pid=os.getpid(), selection=args.task, execute=args.execute, limit=args.limit)
            runner.stage("connect")
            runner.phone = Phone(args.serial)
            runner.log("device_connected")
            tasks = [task for task in TASKS if args.task in {"all", task.key}]
            resume_final_before = (
                runner.final_rewards if args.task != "all" and (args.resume_ad or args.recover_landing) else None
            )
            if args.recover_landing:
                runner.stage("recover_landing")
                component = runner.component()
                if component == APP_LOCK:
                    runner.return_from_app_lock()
                elif (args.task == "promo" and component[0] == MEITUAN and component[1] in {MRN, TRAVEL_DETAIL}
                      and runner.is_promo_landing(component[1], runner.phone.frame())):
                    runner.browse_internal(component[1], 10)
                elif (args.task == "goods" and component[0] == MEITUAN and component[1] in {MRNX, MRN_STANDARD}
                      and (status := runner.goods_card_landing_status(component[1]))):
                    runner.finish_goods_card_landing(component[1], status)
                else:
                    if is_ad_landing(component) and component not in WECHAT_AD_WEB_VIEWS:
                        runner.phone.return_to_game()
                        time.sleep(1.5)
                    elif component in {(MEITUAN, WEB), (MEITUAN, TITANS_WEB), (MEITUAN, DEAL_DETAIL)}:
                        runner.phone.back()
                        time.sleep(1.3)
                    runner.finish_ad_return(True)
            if args.resume_ad:
                runner.stage("resume_ad")
                frame = runner.phone.frame()
                if args.task == "goods" and runner.goods_card_button(frame):
                    runner.browse_goods_card(frame)
                else:
                    runner.full_ad()
            if not args.execute:
                runner.stage("preview")
                image = runner.phone.frame()
                for task in tasks:
                    row = runner.row(image, task)
                    if row:
                        print(f"{task.name}：识别到行，剩余 {runner.remaining(image, task, row[0])} 次。")
                runner.log("run_finished", status="preview")
                return 0
            for task in tasks:
                runner.finish(task, args.limit, resume_final_before=resume_final_before)
            runner.log("run_finished", status="finished")
        return 0
    except KeyboardInterrupt as exc:
        if runner:
            runner.record_stop(exc, "cancelled")
        return 130
    except (Stop, OSError, subprocess.TimeoutExpired, cv2.error) as exc:
        if runner:
            if isinstance(exc, Stop):
                code = exc.code or "state_unconfirmed"
            elif isinstance(exc, subprocess.TimeoutExpired):
                code = "subprocess_timeout"
            elif isinstance(exc, cv2.error):
                code = "image_processing_error"
            else:
                code = "system_error"
            runner.record_stop(exc, code)
        print(f"已停止：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if runner:
            runner.record_stop(exc, "unexpected_error", unexpected=True)
        raise
    finally:
        if runner:
            print(f"运行记录：{runner.run}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
