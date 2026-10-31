# -*- coding: utf-8 -*-
"""鲸鱼桌宠 v3

新增：
- 知道时间（右键问几点；按时段问候；深夜提醒）
- 更多互动（摸头/跳舞/唱歌/翻跟头/喂 token）
- 检测后台音乐（系统音频峰值）→ 戴墨镜左右跳舞 + 音乐符号 → 邀请斗舞 → 音游小游戏
- 检测到你在玩别的游戏 → 缩小站到角落不动
- 长时间没人理 → 变成蓝色（客户端图标蓝）→ 再变扁；碰一下恢复

运行：pythonw desk_pet.py   或双击 start-pet.cmd
"""

import ctypes
import datetime
import json
import math
import os
import queue
import random
import socket
import threading
import time
import tkinter as tk
import urllib.request
from ctypes import wintypes

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageTk

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ---------------- IPv4 优先 ----------------
_orig_gai = socket.getaddrinfo


def _prefer_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    if family not in (0, socket.AF_UNSPEC):
        return _orig_gai(host, port, family, type, proto, flags)
    try:
        infos = _orig_gai(host, port, socket.AF_INET, type, proto, flags)
        if infos:
            return infos
    except socket.gaierror:
        pass
    return _orig_gai(host, port, family, type, proto, flags)


socket.getaddrinfo = _prefer_ipv4

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
ICON_PATH = os.path.join(ASSETS, "my_icon.png")
POS_PATH = os.path.join(HERE, "pet_pos.json")
CONFIG_PATH = os.path.join(HERE, "config.json")
WEATHER_CACHE = os.path.join(HERE, "weather_cache.json")
TOKEN_STATE = os.path.join(HERE, "pet_tokens.json")

KEY = "#010203"
WIN_W, WIN_H = 260, 240
ICON_SIZE = 122
TICK_MS = 55
SPEED_WANDER = 1.1
SPEED_FOLLOW = 2.3
SPEED_DASH = 6.5

BLUE_AFTER = 150.0      # 多久没人理 → 变蓝
FLAT_AFTER = 240.0      # 再久一点 → 变扁
MUSIC_PEAK = 0.02       # 音频峰值阈值
MUSIC_HOLD = 2          # 连续几次峰值 → 认为在放歌
GAME_WHITELIST = {
    "explorer.exe", "deepseek harness.exe", "msedge.exe", "chrome.exe",
    "firefox.exe", "wechat.exe", "weixin.exe", "qq.exe", "tim.exe",
    "python.exe", "pythonw.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "textinputhost.exe", "searchhost.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "applicationframehost.exe",
    "systemsettings.exe", "taskmgr.exe", "mstsc.exe", "code.exe",
    "wesing.exe", "cloudmusic.exe", "sodamusic.exe", "qqmusic.exe",
    "spotify.exe", "potplayermini64.exe", "vlc.exe", "notepad.exe",
}
KNOWN_GAME_HINTS = ("sky.exe", "光遇", "steam", "genshin", "yuanshen",
                    "hitman", "eldenring", "cs2", "dota2", "league",
                    "minecraft", "fevergames", "hero", "noita")

BLUE = (47, 91, 255)

# ---------------- 台词 ----------------
LINES = [
    "我在。", "要不要休息一下？", "我在这儿飘着。", "摸摸我。",
    "你今天很辛苦。", "别熬太晚。", "桌面有点大。", "……（悄悄看你）",
    "深海来的鲸鱼。", "我陪着你。", "发呆中。", "在听歌吗？",
]
PET_LINES = ["唔…", "再摸一下。", "好舒服。", "贴贴。"]
SLEEP_LINES = ["zzz…", "呼……"]
SPOUT_LINES = ["噗——", "喷水！", "看水花。"]
BUBBLE_LINES = ["咕噜咕噜。", "吐个泡泡。", "泡泡。"]
ROLL_LINES = ["翻个身。", "转——", "看我打滚。"]
EAT_LINES = ["嘎嘣。", "token 真好吃。", "好吃。", "…嚼嚼…", "再来一个。", "脆的。"]
MUSIC_LINES = ["♪ 这歌不错。", "有音乐！", "节奏来了。", "♪ 一起摇。"]
IDLE_BLUE_LINES = ["……", "有点无聊。", "在吗。"]
INVITE_LINES = ["敢不敢斗舞？", "来比一场？", "斗舞吗，就现在。"]

WMO = {
    0: "晴", 1: "少云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷雨冰雹", 99: "雷雨冰雹",
}
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
SNOW_CODES = {71, 73, 75, 77, 85, 86}


# ---------------- 工具 ----------------
def _http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def now_str():
    n = datetime.datetime.now()
    return n.strftime("%H:%M")


def time_greeting():
    h = datetime.datetime.now().hour
    if 5 <= h < 11:
        return "早上好。"
    if 11 <= h < 14:
        return "中午好。"
    if 14 <= h < 18:
        return "下午好。"
    if 18 <= h < 23:
        return "晚上好。"
    return "夜深了。"


def time_line():
    h = datetime.datetime.now().hour
    base = "现在 %s。" % now_str()
    if h >= 23 or h < 6:
        return base + "该睡了。"
    if h < 9:
        return base + "早。"
    return base


# ---------------- 前台 / 音频 ----------------
def foreground_info():
    try:
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        hwnd = u.GetForegroundWindow()
        tb = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, tb, 512)
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        h = k.OpenProcess(0x1000, False, pid.value)
        if h:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            k.CloseHandle(h)
            exe = buf.value
        rect = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(rect))
        sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        w, hh = rect.right - rect.left, rect.bottom - rect.top
        return {"title": tb.value, "exe": exe, "pid": pid.value,
                "hwnd": hwnd, "fullscreen": w >= sw * 0.97 and hh >= sh * 0.97}
    except Exception:
        return {"title": "", "exe": "", "pid": 0, "hwnd": 0, "fullscreen": False}


def is_game_foreground(info):
    try:
        base = os.path.basename(info.get("exe") or "").lower()
        title = (info.get("title") or "").lower()
    except Exception:
        return False
    if not base:
        return False
    if base in GAME_WHITELIST:
        return False
    if any(h in base for h in KNOWN_GAME_HINTS):
        return True
    if any(h in title for h in KNOWN_GAME_HINTS):
        return info.get("fullscreen", False)
    return bool(info.get("fullscreen"))


def audio_peak():
    try:
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    except Exception:
        return 0.0
    peak = 0.0
    try:
        for s in AudioUtilities.GetAllSessions():
            try:
                m = s._ctl.QueryInterface(IAudioMeterInformation)
                p = float(m.GetPeakValue())
                if p > peak:
                    peak = p
            except Exception:
                continue
    except Exception:
        return 0.0
    return peak


# ---------------- 天气 ----------------
def fetch_weather():
    cfg = _load_json(CONFIG_PATH, {}) or {}
    lat, lon, city = cfg.get("lat"), cfg.get("lon"), cfg.get("city")
    if lat is None or lon is None:
        try:
            d = _http_json("https://ipwho.is/", 8)
            if d.get("success"):
                lat, lon = d.get("latitude"), d.get("longitude")
                city = city or d.get("city") or d.get("region") or ""
        except Exception:
            pass
    if (lat is None or lon is None) and city:
        try:
            g = _http_json(
                "https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1&language=zh&format=json"
                % urllib.request.quote(city), 8)
            res = (g.get("results") or [None])[0]
            if res:
                lat, lon = res["latitude"], res["longitude"]
                city = res.get("name") or city
        except Exception:
            pass
    if lat is None or lon is None:
        return None
    _save_json(CONFIG_PATH, {"lat": lat, "lon": lon, "city": city})
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%.3f&longitude=%.3f"
               "&current=temperature_2m,weather_code,is_day"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
               "&timezone=auto&forecast_days=1") % (lat, lon)
        d = _http_json(url, 8)
    except Exception:
        return None
    cur = d.get("current") or {}
    daily = d.get("daily") or {}
    code = int(cur.get("weather_code") or 0)
    dcode = int((daily.get("weather_code") or [code])[0] or code)
    data = {
        "city": city or "", "code": code, "desc": WMO.get(code, "未知"),
        "temp": cur.get("temperature_2m"), "is_day": cur.get("is_day", 1),
        "dcode": dcode, "ddesc": WMO.get(dcode, "未知"),
        "tmax": (daily.get("temperature_2m_max") or [None])[0],
        "tmin": (daily.get("temperature_2m_min") or [None])[0],
        "rain": (daily.get("precipitation_probability_max") or [None])[0],
        "ts": time.time(),
    }
    _save_json(WEATHER_CACHE, data)
    return data


def weather_line(w):
    if not w:
        return None
    desc = w.get("desc") or ""
    code = w.get("code", 0)
    t = w.get("temp")
    if code in RAIN_CODES:
        return "外面在下雨，出门记得带伞。"
    if code in SNOW_CODES:
        return "下雪了，小心路滑。"
    if code == 0:
        s = "今天是大晴天。"
        if t is not None and t >= 28:
            s += "有点热，多喝水。"
        return s
    if t is not None:
        if t <= 5:
            return "现在 %d 度，很冷，多穿点。" % round(t)
        if t >= 30:
            return "现在 %d 度，热，注意别中暑。" % round(t)
    if code in (2, 3):
        return "今天多云。"
    return "现在是%s。" % desc


# ---------------- 贴图 ----------------
def load_whale():
    import cv2

    im = Image.open(ICON_PATH).convert("RGBA")
    arr = np.array(im)
    alpha = arr[:, :, 3]
    gray = np.array(im.convert("L"))
    content = alpha > 10
    dark = (content & (gray < 150)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    if n <= 1:
        raise SystemExit("图标里找不到主体")
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    whale = labels == idx
    light = (~whale).astype(np.uint8)
    h, w = light.shape
    ff = light.copy()
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        cv2.floodFill(ff, None, seed, 2)
    outside = ff == 2
    keep = whale | (~outside & ~whale)
    oa = np.where(keep, 255, 0).astype(np.uint8)
    out = im.copy()
    out.putalpha(Image.fromarray(oa))
    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    prem = out.convert("RGBa")
    prem.thumbnail((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    out = prem.convert("RGBA")
    r, g, b, a = out.split()
    a = a.point(lambda v: 255 if v > 100 else 0)
    return Image.merge("RGBA", (r, g, b, a))


def make_blue_whale(whale):
    r, g, b, a = whale.split()
    gray = Image.merge("RGB", (r, g, b)).convert("L")
    tinted = ImageOps.colorize(gray, black=(30, 64, 200), white=(232, 240, 255))
    tinted.putalpha(a)
    return tinted


def find_font(size, bold=False):
    for name in ("msyhbd.ttc" if bold else "msyh.ttc", "msyh.ttc",
                 "simhei.ttf", "arial.ttf"):
        try:
            from PIL import ImageFont
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    from PIL import ImageFont
    return ImageFont.load_default()


def make_bubble(text, fnt, max_w=228):
    tmp = Image.new("RGBA", (WIN_W, 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=fnt) > max_w - 26:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    lines = lines[:3]
    tw = max((d.textlength(l, font=fnt) for l in lines), default=40)
    th = 24 * len(lines) + 18
    w = int(tw + 30)
    x0 = (WIN_W - w) // 2
    y0 = 2
    d.rounded_rectangle([x0, y0, x0 + w, y0 + th], radius=14,
                        fill=(255, 255, 255, 245), outline=(210, 214, 222, 255), width=2)
    for i, line in enumerate(lines):
        d.text((x0 + 15, y0 + 8 + 24 * i), line, font=fnt, fill=(43, 47, 58, 255))
    out = Image.new("RGB", (WIN_W, 94), KEY)
    out.paste(tmp, (0, 0), tmp)
    return out


def make_token(size):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([1, 1, size - 2, size - 2], fill=(255, 204, 84, 255),
              outline=(208, 142, 34, 255), width=max(1, size // 9))
    d.ellipse([size * 0.22, size * 0.22, size * 0.78, size * 0.78],
              outline=(255, 238, 175, 255), width=max(1, size // 16))
    try:
        f = find_font(max(11, int(size * 0.52)), True)
        d.text((size * 0.30, size * 0.12), "T", font=f, fill=(146, 96, 20, 255))
    except Exception:
        pass
    return ImageTk.PhotoImage(im)


# ---------------- 全局键盘钩子 ----------------
class KeyboardHook:
    """低层键盘钩子：斗舞时把 D/F/J/K 截走，避免漏进输入框。"""

    LANES = {0x44: 0, 0x46: 1, 0x4A: 2, 0x4B: 3}  # d f j k
    VK_ESC = 0x1B

    def __init__(self, handler):
        self.handler = handler
        self._hook = None
        self._proc = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        WH_KEYBOARD_LL = 13
        WM_KEYDOWN = 0x0100
        WM_SYSKEYDOWN = 0x0104

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_void_p)]

        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM)

        def proc(nCode, wParam, lParam):
            try:
                if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    handled = self.handler(int(kb.vkCode))
                    if os.environ.get("PET_HOOK_DEBUG"):
                        try:
                            with open(self._log, "a", encoding="utf-8") as f:
                                f.write("vk=%d handled=%s\n" % (int(kb.vkCode), handled))
                        except Exception:
                            pass
                    if handled:
                        return 1
            except Exception:
                pass
            try:
                return user32.CallNextHookEx(None, nCode, wParam, lParam)
            except Exception:
                return 0

        self._proc = proc
        self._callback = HOOKPROC(proc)   # 必须保留引用，且传 WINFUNCTYPE 包装
        self._log = os.path.join(HERE, "hook_debug.log")
        try:
            self._hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._callback, 0, 0)
        except Exception:
            self._hook = None
            return
        if os.environ.get("PET_HOOK_DEBUG"):
            try:
                with open(self._log, "a", encoding="utf-8") as f:
                    f.write("install hook=%r\n" % (self._hook,))
            except Exception:
                pass
        if not self._hook:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


# ---------------- 音游 ----------------
class RhythmGame(tk.Toplevel):
    LANES = ("d", "f", "j", "k")
    COLORS = ("#ff6b9d", "#ffd166", "#5ee6c8", "#7aa2ff")

    def __init__(self, master, on_close, on_lane):
        super().__init__(master)
        self.on_close = on_close
        self.on_lane = on_lane
        self._kb = None
        self.alive = True
        self.title("斗舞 · 音游")
        self.configure(bg="#0e1016")
        self.geometry("520x540+660+220")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.canvas = tk.Canvas(self, width=520, height=470, bg="#0e1016",
                                highlightthickness=0)
        self.canvas.pack()
        self.hit_y = 396
        self.notes = []
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.start = time.time()
        self.duration = 30.0
        self.last = time.time()
        self._draw_stage()
        for i, key in enumerate(self.LANES):
            self.bind("<KeyPress-%s>" % key, lambda e, i=i: self.hit(i))
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(60, self._bring_to_front)
        self.after(300, self._bring_to_front)
        self.after(700, self._bring_to_front)
        self.after(400, self.spawn)
        self.after(16, self.tick)

    def _bring_to_front(self):
        try:
            self.update_idletasks()
            self.lift()
            self.attributes("-topmost", True)
            self.focus_force()
            self.grab_set()
            self._force_foreground()
        except Exception:
            pass

    def _force_foreground(self):
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = self.winfo_id()
            parent = user32.GetParent(hwnd)
            if parent:
                hwnd = parent
            fg = user32.GetForegroundWindow()
            cur = kernel32.GetCurrentThreadId()
            fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
            attached = False
            if fg_thread and fg_thread != cur:
                attached = bool(user32.AttachThreadInput(fg_thread, cur, True))
            user32.ShowWindow(hwnd, 9)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
            if attached:
                user32.AttachThreadInput(fg_thread, cur, False)
        except Exception:
            pass

    def _draw_stage(self):
        c = self.canvas
        for i in range(4):
            x = 70 + i * 100
            c.create_rectangle(x - 34, 40, x + 34, 470,
                               outline="#1e2431", width=2)
            c.create_text(x, 440, text=self.LANES[i].upper(), fill="#8b95a8",
                          font=("Microsoft YaHei", 15, "bold"))
        c.create_line(60, self.hit_y, 460, self.hit_y, fill="#4a5470", width=3)
        self.score_text = c.create_text(16, 16, anchor="nw", text="分数 0  连击 0",
                                        fill="#dfe6f3", font=("Microsoft YaHei", 14, "bold"))
        self.time_text = c.create_text(504, 16, anchor="ne", text="30s",
                                       fill="#8b95a8", font=("Microsoft YaHei", 13))
        c.create_text(260, 18, text="斗舞 · 按 D F J K 接住音符", fill="#6f7a90",
                      font=("Microsoft YaHei", 12))

    def spawn(self):
        if not self.alive:
            return
        lane = random.randrange(4)
        x = 70 + lane * 100
        item = self.canvas.create_rectangle(x - 24, -20, x + 24, 8,
                                            fill=self.COLORS[lane], outline="")
        self.notes.append({"lane": lane, "y": -20.0, "item": item})
        self.after(random.randint(300, 480), self.spawn)

    def tick(self):
        if not self.alive:
            return
        now = time.time()
        dt = min(0.05, now - self.last)
        self.last = now
        speed = 430.0
        for n in list(self.notes):
            n["y"] += speed * dt
            self.canvas.coords(n["item"], 70 + n["lane"] * 100 - 24, n["y"],
                               70 + n["lane"] * 100 + 24, n["y"] + 28)
            if n["y"] > self.hit_y + 70:
                self.notes.remove(n)
                self.canvas.delete(n["item"])
                self.combo = 0
                self.update_hud()
        left = max(0, self.duration - (now - self.start))
        self.canvas.itemconfigure(self.time_text, text="%ds" % int(left))
        if left <= 0:
            self.finish()
            return
        self.after(16, self.tick)

    def hit(self, lane):
        if not self.alive:
            return
        best = None
        for n in self.notes:
            if n["lane"] != lane:
                continue
            if abs(n["y"] - self.hit_y) <= 70:
                if best is None or abs(n["y"] - self.hit_y) < abs(best["y"] - self.hit_y):
                    best = n
        if best:
            self.notes.remove(best)
            self.canvas.delete(best["item"])
            self.combo += 1
            self.max_combo = max(self.max_combo, self.combo)
            self.score += 100 + min(self.combo, 20) * 5
            self.flash(lane, True)
            self.beep(880)
        else:
            self.combo = 0
            self.flash(lane, False)
            self.beep(300)
        self.update_hud()

    def beep(self, freq):
        try:
            import winsound
            winsound.Beep(freq, 25)
        except Exception:
            pass

    def flash(self, lane, ok):
        x = 70 + lane * 100
        color = "#7cffc4" if ok else "#ff5f7a"
        item = self.canvas.create_oval(x - 30, self.hit_y - 30,
                                       x + 30, self.hit_y + 30,
                                       outline=color, width=3)
        self.after(90, lambda: self.canvas.delete(item))

    def update_hud(self):
        self.canvas.itemconfigure(
            self.score_text,
            text="分数 %d  连击 %d" % (self.score, self.combo))

    def finish(self):
        if not self.alive:
            return
        self.alive = False
        self.canvas.create_rectangle(0, 0, 520, 470, fill="#0e1016", stipple="gray25")
        self.canvas.create_text(260, 200, text="结算", fill="#dfe6f3",
                                font=("Microsoft YaHei", 24, "bold"))
        self.canvas.create_text(260, 250,
                                text="得分 %d   最高连击 %d" % (self.score, self.max_combo),
                                fill="#9fb0cc", font=("Microsoft YaHei", 16))
        self.canvas.create_text(260, 300, text="点击这里关闭", fill="#6f7a90",
                                font=("Microsoft YaHei", 12))
        self.canvas.bind("<Button-1>", lambda e: self.close())

    def close(self):
        if self.alive:
            self.alive = False
        if getattr(self, "_kb", None):
            try:
                for key in list(self.LANES) + ["esc"]:
                    self._kb.unhook_key(key)
            except Exception:
                try:
                    self._kb.unhook_all()
                except Exception:
                    pass
            self._kb = None
        try:
            self.destroy()
        except Exception:
            pass
        try:
            self.on_close()
        except Exception:
            pass


# ---------------- 桌宠 ----------------
class Pet:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", KEY)
        self.root.config(bg=KEY)

        self.whale = load_whale()
        self.whale_blue = make_blue_whale(self.whale)
        self.font = find_font(15)
        self.cv = tk.Canvas(self.root, width=WIN_W, height=WIN_H,
                            bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack()

        self._img = None
        self._item_main = self.cv.create_image(0, 0, anchor="nw")
        self._item_bubble = self.cv.create_image(0, 0, anchor="nw")
        self.cv.itemconfigure(self._item_bubble, state="hidden")
        self.token_imgs = [make_token(s) for s in (20, 24, 28)]
        self._item_token = self.cv.create_image(0, 0, anchor="center")
        self.cv.itemconfigure(self._item_token, state="hidden")

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.screen_w, self.screen_h = sw, sh
        x, y = self._load_pos()
        if x is None:
            x, y = sw - WIN_W - 80, sh - WIN_H - 90
        self.x = float(max(0, min(x, sw - WIN_W)))
        self.y = float(max(0, min(y, sh - WIN_H)))
        self.home_x, self.home_y = self.x, self.y
        self.root.geometry(f"{WIN_W}x{WIN_H}+{int(self.x)}+{int(self.y)}")

        self.phase = 0
        self.facing = 1
        self.state = "idle"       # idle / sleep / happy / watch / flat
        self.action = None
        self.action_until = 0.0
        self.state_until = time.time() + 2.0
        self.target = None
        self.bubble_until = 0.0
        self.bubble_cache = {}
        self.follow_cursor = False
        self.dragging = False
        self.drag_dx = self.drag_dy = 0
        self.press_time = 0.0
        self.next_curious = time.time() + 20
        self.curious_until = 0.0
        self.next_action = time.time() + 8
        self.weather = _load_json(WEATHER_CACHE, None)
        self.next_weather_talk = time.time() + 40
        self.tokens_eaten = int((_load_json(TOKEN_STATE, {}) or {}).get("tokens", 0))
        self.token = None
        self.next_token = time.time() + random.uniform(16, 34)
        self.last_interaction = time.time()
        self.music_playing = False
        self.music_since = 0.0
        self.music_stop = 0.0
        self.dance_until = 0.0
        self.invite_at = 0.0
        self.invite = None
        self.rhythm = None
        self.game_mode = False
        self.watch_pos = None
        self.next_blue_talk = 0.0
        self.next_time_talk = time.time() + 120
        self.next_music_poll = 0.0
        self.next_game_poll = 0.0
        self.audio_peak_val = 0.0
        self.audio_hits = 0
        self.test_blue = False
        self.key_queue = queue.Queue()
        self.key_hook = KeyboardHook(self._hook_key)

        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<Double-Button-1>", self.on_double)
        self.cv.bind("<Button-3>", self.on_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="现在几点了", command=self.say_time)
        self.menu.add_command(label="天气怎么样", command=self.say_weather)
        self.menu.add_command(label="喂它一个 token", command=self.feed_token)
        self.menu.add_command(label="已吃掉 0 枚 token")
        self._token_count_index = 3
        self.menu.add_separator()
        self.menu.add_command(label="摸摸头", command=self.pet_head)
        self.menu.add_command(label="跳个舞", command=lambda: self.start_dance(4.0, True))
        self.menu.add_command(label="唱首歌", command=self.sing)
        self.menu.add_command(label="翻跟头", command=lambda: self.do_action("roll"))
        self.menu.add_command(label="斗舞（放歌时可用）", command=self.invite_dance)
        self.menu.add_separator()
        self.menu.add_command(label="睡觉", command=self.go_sleep)
        self.menu.add_command(label="起床", command=self.wake)
        self.menu.add_command(label="跟随鼠标：开/关", command=self.toggle_follow)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.quit)

        self._build_frames()
        threading.Thread(target=self._weather_thread, daemon=True).start()
        threading.Thread(target=self._music_thread, daemon=True).start()
        threading.Thread(target=self._game_thread, daemon=True).start()

        self.root.after(200, self.tick)
        self.root.after(1600, lambda: self.say(time_greeting(), 3.2))
        self._test_hooks()

    def _test_hooks(self):
        if os.environ.get("PET_TOKEN_NOW"):
            self.root.after(1200, lambda: self.spawn_token(announce=True))
        if os.environ.get("PET_TEST_MUSIC"):
            self.root.after(1500, self._force_music)
        if os.environ.get("PET_TEST_FLAT"):
            self.root.after(1500, self._force_flat)
        if os.environ.get("PET_TEST_BLUE"):
            self.test_blue = True
            self.root.after(1500, self._force_flat)
        if os.environ.get("PET_TEST_RHYTHM"):
            self.root.after(2000, self.start_rhythm)
        if os.environ.get("PET_TEST_GAME"):
            self.root.after(1500, lambda: setattr(self, "game_mode", True))

    def _force_music(self):
        self.music_playing = True
        self.music_since = time.time()
        self.dance_until = time.time() + 14
        self.invite_at = time.time() + 3.5

    def _force_flat(self):
        self.last_interaction = time.time() - FLAT_AFTER - 10

    # ---------- 帧 ----------
    def _frame(self, whale=None, angle=0.0, scale=1.0, dim=255, facing=1,
               hearts=False, spout=-1, bubbles=0, trail=False, zzz=False,
               sunglasses=False, notes=0, squash=1.0, hop=0):
        canvas = Image.new("RGB", (WIN_W, WIN_H), KEY)
        w = whale if whale is not None else self.whale
        if dim < 255:
            r, g, b, a = w.split()
            a = a.point(lambda v: int(v * dim / 255))
            w = Image.merge("RGBA", (r, g, b, a))
        if facing < 0:
            w = w.transpose(Image.FLIP_LEFT_RIGHT)
        if scale != 1.0:
            w = w.resize((max(1, int(w.width * scale)),
                          max(1, int(w.height * scale))), Image.LANCZOS)
        if squash != 1.0:
            w = w.resize((w.width, max(1, int(w.height * squash))), Image.LANCZOS)
        if angle:
            w = w.rotate(angle, expand=True, resample=Image.BICUBIC)
        cx = WIN_W // 2 + hop
        cy = 150
        if squash < 0.6:
            cy += 66
        canvas.paste(w, (cx - w.width // 2, cy - w.height // 2), w)
        d = ImageDraw.Draw(canvas)

        for (sx, sy, c) in (
                (cx - 70, cy - 42, (150, 205, 240)),
                (cx + 66, cy + 8, (255, 212, 138)),
                (cx - 46, cy + 50, (255, 165, 182))):
            d.ellipse([sx - 2, sy - 2, sx + 2, sy + 2], fill=c)

        top = cy - w.height // 2
        if sunglasses:
            ey = top + int(w.height * 0.34)
            d.rounded_rectangle([cx - 30, ey - 7, cx - 6, ey + 7], radius=6,
                                fill=(20, 20, 26))
            d.rounded_rectangle([cx + 6, ey - 7, cx + 30, ey + 7], radius=6,
                                fill=(20, 20, 26))
            d.line([cx - 6, ey, cx + 6, ey], fill=(20, 20, 26), width=4)
        if notes:
            for i in range(notes):
                a = self.phase / 5 + i * 2.1
                nx = cx + math.cos(a) * 64
                ny = cy + math.sin(a) * 42 - 8
                col = (90, 150, 240) if i % 2 == 0 else (240, 120, 180)
                self._draw_note(d, nx, ny, col, 1.0 if i % 2 == 0 else 0.85)
        if spout >= 0:
            for i in range(6):
                ang = -90 + (i - 2.5) * 18
                r = 16 + spout * 8
                sx = cx + math.cos(math.radians(ang)) * r
                sy = top - 4 - spout * 7 + math.sin(math.radians(ang)) * r * 0.45
                d.ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=(150, 205, 235))
        if trail:
            for i in range(4):
                tx = cx - facing * (w.width // 2 + 14 + i * 12)
                ty = cy + 10 + math.sin(self.phase / 2 + i) * 6
                d.ellipse([tx - 3, ty - 3, tx + 3, ty + 3], fill=(160, 210, 240))
        if bubbles:
            for i in range(bubbles):
                bx = cx + 38 + i * 9
                by = top + 18 - ((self.phase * 3 + i * 12) % 70)
                rr = 3 + (i % 3)
                d.ellipse([bx - rr, by - rr, bx + rr, by + rr],
                          outline=(170, 215, 245), width=2)
        if hearts:
            for (hx, hy, s) in ((-52, -30, 7), (48, -22, 6), (0, -46, 8)):
                self._heart(d, cx + hx, cy + hy, s)
        if zzz:
            f = find_font(18, True)
            d.text((cx + 44, top - 12), "z", font=f, fill=(160, 180, 210))
            d.text((cx + 56, top - 26), "Z", font=f, fill=(120, 145, 185))
        return ImageTk.PhotoImage(canvas)

    @staticmethod
    def _draw_note(d, x, y, col, scale=1.0):
        r = 5 * scale
        d.ellipse([x - r, y - r * 0.7, x + r, y + r * 0.7], fill=col)
        d.line([x + r - 1, y - 2, x + r - 1, y - 20 * scale], fill=col,
               width=max(1, int(2 * scale)))
        d.line([x + r - 1, y - 20 * scale, x + r + 7 * scale, y - 13 * scale],
               fill=col, width=max(1, int(2 * scale)))

    @staticmethod
    def _heart(d, x, y, s):
        c = (255, 120, 150)
        d.ellipse([x - s // 2, y - s // 2, x + s // 2, y + s // 2], fill=c)
        d.ellipse([x + s // 2 - 1, y - s // 2, x + s + 2, y + s // 2], fill=c)
        d.polygon([(x - s // 2, y + 2), (x + s, y + 2), (x + s // 4, y + s + 6)], fill=c)

    def _build_frames(self):
        self.f_float = [self._frame(angle=a, scale=s)
                        for a in (-5, -2, 1, 4, 1, -2) for s in (1.0, 1.03)]
        self.f_float_l = [self._frame(angle=a, scale=s, facing=-1)
                          for a in (-5, -2, 1, 4, 1, -2) for s in (1.0, 1.03)]
        self.f_roll = [self._frame(angle=a) for a in range(0, 360, 30)]
        self.f_roll_l = [self._frame(angle=a, facing=-1) for a in range(0, 360, 30)]
        self.f_dash = [self._frame(angle=9, trail=True) for _ in range(3)]
        self.f_dash_l = [self._frame(angle=-9, facing=-1, trail=True) for _ in range(3)]
        self.f_bubbles = [self._frame(bubbles=n) for n in (2, 3, 4, 5, 4, 3)]
        self.f_stretch = [self._frame(scale=s) for s in (0.92, 1.07, 1.0, 0.95, 1.04, 1.0)]
        self.f_spout = [self._frame(spout=i) for i in range(6)]
        self.f_hearts = [self._frame(hearts=True, scale=s) for s in (1.0, 1.05, 1.0)]
        self.f_sleep = [self._frame(angle=a, dim=110, zzz=True) for a in (-3, 0, 3)]
        # 蓝色 / 蓝色变扁
        self.f_blue = [self._frame(whale=self.whale_blue, angle=a, scale=s)
                       for a in (-4, 0, 4) for s in (1.0, 1.02)]
        self.f_flat = [self._frame(whale=self.whale_blue, angle=a,
                                   squash=0.36, scale=1.06)
                       for a in (-3, 0, 3)]
        # 游戏时缩小站边
        self.f_small = [self._frame(scale=0.52, angle=a) for a in (-4, 0, 4)]
        self.f_small_l = [self._frame(scale=0.52, angle=a, facing=-1) for a in (-4, 0, 4)]
        self.f_sing = [self._frame(notes=3, angle=a) for a in (-4, 0, 4)]

    # ---------- 位置 ----------
    def _load_pos(self):
        d = _load_json(POS_PATH, {})
        try:
            return int(d["x"]), int(d["y"])
        except Exception:
            return None, None

    def _save_pos(self):
        _save_json(POS_PATH, {"x": int(self.x), "y": int(self.y)})

    def _clamp(self):
        self.x = max(-30, min(self.x, self.screen_w - WIN_W + 30))
        self.y = max(0, min(self.y, self.screen_h - WIN_H + 10))

    # ---------- 交互 ----------
    def touch(self):
        self.last_interaction = time.time()

    def on_press(self, e):
        self.touch()
        self.press_time = time.time()
        self.dragging = True
        self.drag_dx, self.drag_dy = e.x, e.y
        self.root.lift()

    def on_drag(self, e):
        if not self.dragging:
            return
        self.touch()
        self.x = e.x_root - self.drag_dx
        self.y = e.y_root - self.drag_dy
        self._clamp()
        self.root.geometry(f"{WIN_W}x{WIN_H}+{int(self.x)}+{int(self.y)}")

    def on_release(self, e):
        if self.dragging and time.time() - self.press_time < 0.3:
            if self.rhythm is not None:
                pass
            elif self.music_playing:
                self.invite_dance()
            else:
                self.pet_head()
        self.dragging = False
        self._save_pos()

    def on_double(self, e):
        self.touch()
        self.dragging = False
        self.do_action("spout")
        self.say(random.choice(SPOUT_LINES), 2.0)

    def on_menu(self, e):
        self.touch()
        try:
            self.menu.entryconfigure(
                self._token_count_index,
                label="已吃掉 %d 枚 token" % self.tokens_eaten)
        except Exception:
            pass
        self.last_interaction = time.time()
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    # ---------- 动作 ----------
    def do_action(self, name, dur=None):
        durs = {"spout": 1.2, "roll": 1.6, "bubbles": 3.0,
                "stretch": 2.0, "dash": 0.8, "hearts": 1.6, "sing": 2.4}
        self.action = name
        self.action_until = time.time() + (dur or durs.get(name, 1.5))
        if name == "dash" and self.state not in ("sleep", "watch"):
            self.target = (random.uniform(20, self.screen_w - WIN_W - 20),
                           self.y + random.uniform(-80, 80))

    def pet_head(self):
        self.touch()
        self.state = "happy"
        self.state_until = time.time() + 2.0
        self.say(random.choice(PET_LINES), 3)

    def sing(self):
        self.touch()
        self.do_action("sing", 2.6)
        self.say(random.choice(["♪ 啦啦啦。", "♪ 给你唱一句。", "♫ 哼哼。"]), 3)

    def say_time(self):
        self.touch()
        self.say(time_line(), 4)

    def say_random(self):
        self.touch()
        if random.random() < 0.22:
            self.say("已经吃掉 %d 枚 token 了。" % self.tokens_eaten, 3.5)
        elif random.random() < 0.25:
            self.say(time_line(), 3.5)
        else:
            self.say(random.choice(LINES), 3.5)

    def say_weather(self):
        self.touch()
        w = self.weather
        if not w:
            self.say("还没定位到天气，等一下再问我。", 3.5)
            return
        line = weather_line(w) or "天气数据没拿到。"
        parts = [line]
        if w.get("tmin") is not None and w.get("tmax") is not None:
            parts.append("今天 %d~%d 度。" % (round(w["tmin"]), round(w["tmax"])))
        self.say("".join(parts), 4.5)

    def go_sleep(self):
        self.touch()
        self.state = "sleep"
        self.state_until = time.time() + 60
        self.target = None
        self.action = None
        self.say(random.choice(SLEEP_LINES), 2.5)

    def wake(self):
        self.touch()
        self.state = "idle"
        self.state_until = time.time() + 1.5
        self.say("醒了。" if not self.game_mode else "……", 2)

    def toggle_follow(self):
        self.touch()
        self.follow_cursor = not self.follow_cursor
        self.say("跟着你。" if self.follow_cursor else "我自己玩。", 2.5)

    def quit(self):
        self._save_pos()
        self.root.destroy()

    # ---------- token ----------
    def save_tokens(self):
        _save_json(TOKEN_STATE, {"tokens": self.tokens_eaten})

    def spawn_token(self, announce=False):
        if self.token is not None or self.rhythm is not None:
            return
        self.token = {"x": random.uniform(32, WIN_W - 32),
                      "y": random.uniform(18, 118),
                      "state": "idle",
                      "life": random.randint(60, 140),
                      "until": time.time() + 14.0}
        if announce or random.random() < 0.3:
            self.say("有 token。", 1.6)

    def feed_token(self):
        self.touch()
        if self.token is None:
            self.spawn_token(announce=True)
            self.say("给我 token！", 2.0)
        else:
            self.say("嘴里还有。", 1.8)

    def _eat_token(self):
        self.token = None
        self.tokens_eaten += 1
        self.save_tokens()
        self.cv.itemconfigure(self._item_token, state="hidden")
        self.do_action("stretch", 1.1)
        if self.tokens_eaten % 10 == 0:
            self.say("已经吃掉 %d 枚 token 了。" % self.tokens_eaten, 3.2)
        else:
            self.say(random.choice(EAT_LINES), 2.0)

    # ---------- 音乐 / 跳舞 / 音游 ----------
    def start_dance(self, dur=999.0, manual=False):
        if manual:
            self.touch()
        self.music_playing = self.music_playing or manual
        self.music_since = self.music_since or time.time()
        self.dance_until = time.time() + dur
        if manual:
            self.say(random.choice(MUSIC_LINES), 2.5)

    def invite_dance(self):
        self.touch()
        if self.rhythm is not None or self.invite is not None:
            return
        self.show_invite()

    def show_invite(self):
        try:
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            w.configure(bg="#f6f8fc", highlightthickness=1,
                        highlightbackground="#c9d3e4")
            w.geometry("200x112+%d+%d" % (
                max(10, int(self.x) - 20),
                max(10, int(self.y) - 110)))
            tk.Label(w, text="斗舞？", bg="#f6f8fc", fg="#2b2f3a",
                     font=("Microsoft YaHei", 13, "bold")).pack(pady=(10, 6))
            row = tk.Frame(w, bg="#f6f8fc")
            row.pack()
            tk.Button(row, text="开始斗舞", bg="#4c6fff", fg="white",
                      relief="flat", font=("Microsoft YaHei", 10, "bold"),
                      command=self.start_rhythm).pack(side="left", padx=4)
            tk.Button(row, text="算了", bg="#e6ebf5", fg="#2b2f3a",
                      relief="flat", font=("Microsoft YaHei", 10),
                      command=self.close_invite).pack(side="left", padx=4)
            self.invite = w
            self.say(random.choice(INVITE_LINES), 3.5)
        except Exception:
            self.invite = None

    def close_invite(self):
        if self.invite is not None:
            try:
                self.invite.destroy()
            except Exception:
                pass
            self.invite = None

    def start_rhythm(self):
        self.touch()
        self.close_invite()
        if self.rhythm is not None:
            return
        try:
            self.watch_pos = (self.x, self.y)
            self.rhythm = RhythmGame(self.root, self.on_rhythm_close, self._queue_lane)
            self.state = "watch"
            self.target = None
            self.action = None
            self.say("该你了。", 2.0)
        except Exception:
            self.rhythm = None

    def on_rhythm_close(self):
        self.rhythm = None
        self.state = "idle"
        self.state_until = time.time() + 1.5
        self.say("跳得不错。" if random.random() < 0.5 else "再来一局？", 3)

    # ---------- 蓝色/变扁 ----------
    def enter_blue(self):
        if self.state not in ("blue", "flat"):
            self.state = "blue"
            self.next_blue_talk = time.time() + random.uniform(40, 90)
        if time.time() - self.last_interaction > FLAT_AFTER:
            if self.state != "flat":
                self.state = "flat"
                self._save_pos()
                # 贴到屏幕底部
                self.y = self.screen_h - WIN_H + 10
                self.x = max(10, min(self.x, self.screen_w - WIN_W - 10))
                self.root.geometry(f"{WIN_W}x{WIN_H}+{int(self.x)}+{int(self.y)}")

    def leave_blue(self):
        if self.state in ("blue", "flat"):
            self.state = "idle"
            self.state_until = time.time() + 1.5
            self.y = min(self.y, self.screen_h - WIN_H - 40)
            self._clamp()
            self.root.geometry(f"{WIN_W}x{WIN_H}+{int(self.x)}+{int(self.y)}")
            self.say("……醒了。", 2.2)

    # ---------- 线程 ----------
    def _weather_thread(self):
        while True:
            try:
                w = fetch_weather()
                if w:
                    self.weather = w
            except Exception:
                pass
            time.sleep(1800)

    def _music_thread(self):
        while True:
            try:
                p = audio_peak()
                self.audio_peak_val = p
                if p > MUSIC_PEAK:
                    self.audio_hits = min(self.audio_hits + 1, 10)
                    self.music_stop = time.time()
                else:
                    self.audio_hits = max(self.audio_hits - 1, 0)
                if self.audio_hits >= MUSIC_HOLD:
                    if not self.music_playing:
                        self.music_playing = True
                        self.music_since = time.time()
                        self.dance_until = self.music_since + 12
                        self.invite_at = self.music_since + 3.0
                elif self.audio_hits == 0 and self.music_playing:
                    if time.time() - self.music_stop > 8:
                        self.music_playing = False
                        self.dance_until = 0
            except Exception:
                pass
            time.sleep(1.1)

    def _game_thread(self):
        while True:
            try:
                info = foreground_info()
                on_game = is_game_foreground(info)
                if on_game != self.game_mode:
                    self.game_mode = on_game
            except Exception:
                pass
            time.sleep(2.0)

    # ---------- 全局按键 ----------
    def _queue_lane(self, lane):
        try:
            self.key_queue.put_nowait(lane)
        except Exception:
            pass

    def _hook_key(self, vk):
        if self.rhythm is None:
            return False
        if vk == KeyboardHook.VK_ESC:
            try:
                self.key_queue.put_nowait(-1)
            except Exception:
                pass
            return True
        lane = KeyboardHook.LANES.get(vk)
        if lane is None:
            return False
        try:
            self.key_queue.put_nowait(lane)
        except Exception:
            pass
        return True

    # ---------- 气泡 ----------
    def say(self, text, secs=3.0):
        self.bubble_until = time.time() + secs
        if text not in self.bubble_cache:
            self.bubble_cache[text] = ImageTk.PhotoImage(make_bubble(text, self.font))
        self.cv.itemconfigure(self._item_bubble,
                              image=self.bubble_cache[text], state="normal")

    # ---------- 主循环 ----------
    def tick(self):
        try:
            now = time.time()
            self.phase += 1
            if self.test_blue:
                self.music_playing = False
                self.last_interaction = now - FLAT_AFTER - 10

            while True:
                try:
                    lane = self.key_queue.get_nowait()
                except queue.Empty:
                    break
                if self.rhythm is not None:
                    try:
                        if lane == -1:
                            self.rhythm.close()
                        else:
                            self.rhythm.hit(lane)
                    except Exception:
                        pass
            sleeping = self.state == "sleep"
            in_rhythm = self.rhythm is not None
            if in_rhythm:
                try:
                    if not self.rhythm.winfo_exists():
                        raise RuntimeError("stale")
                except Exception:
                    self.rhythm = None
                    in_rhythm = False
                    self.state = "idle"
                    self.state_until = time.time() + 1.0
            in_game = self.game_mode and not in_rhythm

            # 状态计时
            if self.state == "happy" and now > self.state_until:
                self.state = "idle"
                self.state_until = now + 1.5
            if self.action and now > self.action_until:
                self.action = None
            if self.state in ("blue", "flat") and now - self.last_interaction < 6:
                self.leave_blue()

            if now > self.bubble_until:
                self.cv.itemconfigure(self._item_bubble, state="hidden")

            # 音乐检测 → 跳舞/邀请
            if self.music_playing and not sleeping and not in_game and not in_rhythm:
                if self.dance_until < now:
                    self.dance_until = now + 12
                if self.invite_at and now > self.invite_at and self.invite is None and self.rhythm is None:
                    self.invite_at = 0
                    self.show_invite()
            if not self.music_playing and self.invite is not None:
                self.close_invite()

            # 玩游戏 → 缩小站到左下角
            if in_game:
                if self.state != "watch" or self.watch_pos is None:
                    self.watch_pos = (self.x, self.y)
                self.state = "watch"
                tx = 24
                ty = self.screen_h - WIN_H - 20
                self.x += (tx - self.x) * 0.22
                self.y += (ty - self.y) * 0.22
                self._clamp()
                self.root.geometry(f"{WIN_W}x{WIN_H}+{int(self.x)}+{int(self.y)}")
            else:
                if self.state == "watch" and not in_rhythm:
                    self.state = "idle"
                    self.state_until = now + 1.5
                    if self.watch_pos:
                        self.x, self.y = self.watch_pos
                        self.watch_pos = None
                        self._clamp()
                        self.root.geometry(f"{WIN_W}x{WIN_H}+{int(self.x)}+{int(self.y)}")

            # 音游时：缩小 + 停在旁边
            if in_rhythm:
                self.x += (40 - self.x) * 0.2
                self.y += ((self.screen_h - WIN_H - 30) - self.y) * 0.2
                self.root.geometry(f"{WIN_W}x{WIN_H}+{int(self.x)}+{int(self.y)}")

            # 长时间没人理 → 变蓝 → 变扁
            idle_secs = now - self.last_interaction
            if (not in_game and not in_rhythm and not self.music_playing
                    and not sleeping and idle_secs > BLUE_AFTER):
                self.enter_blue()
                if self.state == "blue" and now > self.next_blue_talk:
                    self.next_blue_talk = now + random.uniform(40, 90)
                    self.say(random.choice(IDLE_BLUE_LINES), 2.5)

            # 随机动作 / 好奇 / 移动（正常状态才动）
            normal = (not sleeping and not in_game and not in_rhythm
                      and self.state not in ("blue", "flat")
                      and not self.music_playing)

            if normal and now > self.next_action:
                self.next_action = now + random.uniform(9, 22)
                act = random.choices(
                    ["dash", "roll", "bubbles", "stretch", "spout", "hearts"],
                    weights=[3, 2, 2, 2, 2, 1])[0]
                self.do_action(act)
                if random.random() < 0.4:
                    self.say(random.choice(
                        {"roll": ROLL_LINES, "bubbles": BUBBLE_LINES,
                         "spout": SPOUT_LINES}.get(act, LINES)), 2.2)

            if normal:
                if now > self.next_curious:
                    self.next_curious = now + random.uniform(20, 40)
                    self.curious_until = now + 5.5
                cx = self.x + WIN_W / 2
                cy = self.y + WIN_H / 2
                px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
                dist = math.hypot(px - cx, py - cy)

                if self.follow_cursor:
                    self.target = (px - WIN_W / 2 + 8, py - WIN_H / 2 + 20)
                elif now < self.curious_until and dist < 520:
                    self.target = (px - WIN_W / 2, py - WIN_H / 2)
                elif self.target is None and now > self.state_until and not self.dragging:
                    if random.random() < 0.5:
                        self.target = (random.uniform(20, self.screen_w - WIN_W - 20),
                                       random.uniform(self.screen_h * 0.4,
                                                      self.screen_h - WIN_H - 30))
                    else:
                        self.state = "idle"
                    self.state_until = now + random.uniform(2.0, 4.5)

                if self.target and not self.dragging:
                    tx, ty = self.target
                    dx, dy = tx - self.x, ty - self.y
                    d = math.hypot(dx, dy)
                    if d < 6:
                        self.target = None
                        self.state = "idle"
                        self.state_until = now + random.uniform(1.5, 3.5)
                    else:
                        if self.action == "dash":
                            sp = SPEED_DASH
                        elif self.follow_cursor or now < self.curious_until:
                            sp = SPEED_FOLLOW
                        else:
                            sp = SPEED_WANDER
                        step = min(sp, d)
                        self.x += dx / d * step
                        self.y += dy / d * step
                        self._clamp()
                        self.root.geometry(f"{WIN_W}x{WIN_H}+{int(self.x)}+{int(self.y)}")
                        if dx > 0.5:
                            self.facing = 1
                        elif dx < -0.5:
                            self.facing = -1
                else:
                    px2 = self.root.winfo_pointerx()
                    self.facing = 1 if px2 >= self.x + WIN_W / 2 else -1

            # token 逻辑
            if (self.token is None and normal and not sleeping
                    and now > self.next_token):
                self.spawn_token()
                self.next_token = now + random.uniform(20, 45)
            if self.token:
                t = self.token
                if t["state"] == "idle":
                    t["life"] -= 1
                    t["y"] += math.sin(self.phase / 6) * 0.6
                    if t["life"] <= 0 or now > t["until"]:
                        t["state"] = "eat"
                else:
                    mx, my = WIN_W // 2, 116
                    tdx, tdy = mx - t["x"], my - t["y"]
                    td = math.hypot(tdx, tdy)
                    if td < 16:
                        self._eat_token()
                    else:
                        step = min(10.0, td)
                        t["x"] += tdx / td * step
                        t["y"] += tdy / td * step
                if self.token:
                    self.cv.coords(self._item_token, int(t["x"]), int(t["y"]))
                    self.cv.itemconfigure(
                        self._item_token,
                        image=self.token_imgs[(self.phase // 4) % len(self.token_imgs)],
                        state="normal")
            else:
                self.cv.itemconfigure(self._item_token, state="hidden")

            # 选帧
            if self.state == "flat":
                frame = self.f_flat[self.phase // 8 % len(self.f_flat)]
            elif self.state == "blue":
                frame = self.f_blue[self.phase // 7 % len(self.f_blue)]
            elif in_rhythm:
                frame = self.f_small[self.phase // 8 % len(self.f_small)]
            elif in_game or self.state == "watch":
                seq = self.f_small_l if self.facing < 0 else self.f_small
                frame = seq[self.phase // 8 % len(seq)]
            elif sleeping:
                frame = self.f_sleep[self.phase // 10 % len(self.f_sleep)]
            elif self.music_playing and self.state != "happy":
                hop = -10 if (self.phase // 5) % 2 == 0 else 10
                tilt = -8 if hop < 0 else 8
                frame = self._dance_frame(hop, tilt, notes=3 + (self.phase // 5) % 2)
            elif self.state == "happy":
                frame = self.f_hearts[self.phase // 5 % len(self.f_hearts)]
            elif self.action == "spout":
                idx = int((self.action_until - now) * 6) % len(self.f_spout)
                frame = self.f_spout[min(idx, len(self.f_spout) - 1)]
            elif self.action == "roll":
                idx = int((self.action_until - now) * 8) % len(self.f_roll)
                frame = (self.f_roll_l if self.facing < 0 else self.f_roll)[idx]
            elif self.action == "bubbles":
                frame = self.f_bubbles[self.phase // 6 % len(self.f_bubbles)]
            elif self.action == "stretch":
                frame = self.f_stretch[self.phase // 7 % len(self.f_stretch)]
            elif self.action == "hearts":
                frame = self.f_hearts[self.phase // 5 % len(self.f_hearts)]
            elif self.action == "sing":
                frame = self.f_sing[self.phase // 7 % len(self.f_sing)]
            elif self.action == "dash":
                seq = self.f_dash_l if self.facing < 0 else self.f_dash
                frame = seq[self.phase // 2 % len(seq)]
            else:
                seq = self.f_float_l if self.facing < 0 else self.f_float
                frame = seq[self.phase // 5 % len(seq)]

            if frame is not self._img:
                self._img = frame
                self.cv.itemconfigure(self._item_main, image=frame)

            # 偶尔聊时间/天气
            if normal:
                if now > self.next_time_talk:
                    self.next_time_talk = now + random.uniform(300, 600)
                    if random.random() < 0.6:
                        self.say(time_line(), 3.5)
                if now > self.next_weather_talk and self.weather:
                    self.next_weather_talk = now + random.uniform(240, 480)
                    if random.random() < 0.45:
                        line = weather_line(self.weather)
                        if line:
                            self.say(line, 4)

        except Exception:
            if os.environ.get("PET_DEBUG"):
                import traceback
                traceback.print_exc()
        finally:
            self.root.after(TICK_MS, self.tick)

    def _dance_frame(self, hop, tilt, notes=3):
        key = (hop, tilt, notes)
        if not hasattr(self, "_dance_cache"):
            self._dance_cache = {}
        if key not in self._dance_cache:
            self._dance_cache[key] = self._frame(
                hop=hop, angle=tilt, sunglasses=True, notes=notes, scale=1.04)
        return self._dance_cache[key]

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Pet().run()
