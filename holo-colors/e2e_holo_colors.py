"""ホロカラーの通しの確認(Windows だけ)。本物のキー入力とクリックで exe を動かす。
    build.bat を流してから:  python holo-colors/e2e_holo_colors.py
確かめること: 呼び出しのキーで開く・検索して Enter / 札のクリックでコピー・コピーしたら閉じて元の窓へ戻る(すぐ Ctrl+V で貼れる)・
キーをもう一度 / Esc で閉じる・2つ目の起動は動いているほうを開く・閉じない設定・--quit で終わる。
テストの間はマウスとキーボードに触らない(本物の入力を送るため)。クリップボードの文字は終わったら元に戻す。
普段使っているホロカラーとぶつからないように、別の作業データ(一時フォルダ)と別のキー(Ctrl+Alt+Shift+F11)で動かす。"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
TITLE = "ホロカラー"
HOTKEY_MODS, HOTKEY_VK = 0x2 | 0x1 | 0x4, 0x7A   # Ctrl+Alt+Shift+F11

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


KEYUP, UNICODE = 0x2, 0x4
VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "enter": 0x0D, "esc": 0x1B, "v": 0x56}
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
user32.EnumChildWindows.argtypes = (wintypes.HWND, WNDENUMPROC, wintypes.LPARAM)
user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
user32.OpenClipboard.argtypes = (wintypes.HWND,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = (wintypes.UINT,)
user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
user32.SetProcessDPIAware()


def send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
        raise OSError("SendInput が失敗: %d" % ctypes.get_last_error())


def key(vk, up=False):
    return INPUT(type=1, u=_U(ki=KEYBDINPUT(wVk=vk, dwFlags=KEYUP if up else 0)))


def press(*vks):
    send(*[key(v) for v in vks], *[key(v, True) for v in reversed(vks)])


def hotkey():
    mods = [VK["ctrl"], VK["alt"], VK["shift"]]
    press(*mods, HOTKEY_VK)


def type_text(s):
    ins = []
    for ch in s:
        ins.append(INPUT(type=1, u=_U(ki=KEYBDINPUT(wScan=ord(ch), dwFlags=UNICODE))))
        ins.append(INPUT(type=1, u=_U(ki=KEYBDINPUT(wScan=ord(ch), dwFlags=UNICODE | KEYUP))))
    send(*ins)


def click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    send(INPUT(type=0, u=_U(mi=MOUSEINPUT(dwFlags=0x2))), INPUT(type=0, u=_U(mi=MOUSEINPUT(dwFlags=0x4))))


def get_clipboard():
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("クリップボードを開けない")
    try:
        h = user32.GetClipboardData(13)   # CF_UNICODETEXT
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_clipboard(text):
    data = (text or "").encode("utf-16-le") + b"\0\0"
    for _ in range(20):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return
    try:
        user32.EmptyClipboard()
        if text is None:
            return
        h = kernel32.GlobalAlloc(0x2, len(data))
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(13, h)
    finally:
        user32.CloseClipboard()


def window_text(h):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, buf, 512)
    return buf.value


def find_window(pid, title):
    found = []

    def cb(h, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and window_text(h) == title:
            found.append(h)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def children(h):
    out = []

    def cb(c, _):
        out.append(c)
        return True

    user32.EnumChildWindows(h, WNDENUMPROC(cb), 0)
    return out


class Failure(Exception):
    pass


class E2E:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="holo-colors-e2e-")
        self.app_dir = os.path.join(self.tmp, "app")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.app_dir)
        for f in ("HoloColors.exe", "members.json"):
            shutil.copy2(os.path.join(BUILD, f), self.app_dir)
        self.exe = os.path.join(self.app_dir, "HoloColors.exe")
        with open(os.path.join(self.app_dir, "members.json"), encoding="utf-8") as f:
            self.members = json.load(f)
        self.proc = None
        self.passed = 0
        self.root = tk.Tk()
        self.root.title("e2e: 前の窓")
        self.root.geometry("420x120+60+60")
        self.entry = tk.Entry(self.root, width=40)
        self.entry.pack(padx=20, pady=30)
        self.pump(0.3)
        self.tk_hwnd = user32.GetAncestor(self.root.winfo_id(), 2)   # GA_ROOT

    def pump(self, seconds):
        end = time.time() + seconds
        while True:
            self.root.update()
            if time.time() >= end:
                return
            time.sleep(0.02)

    def wait(self, what, cond, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            self.root.update()
            v = cond()
            if v:
                return v
            time.sleep(0.03)
        raise Failure("待っても来ない: " + what)

    def check(self, cond, what):
        if not cond:
            raise Failure(what)
        self.passed += 1
        print("ok   ", what)

    def write_settings(self, **kw):
        s = {"hotkeyModifiers": HOTKEY_MODS, "hotkeyKey": HOTKEY_VK, "closeAfterCopy": True, "includeHash": True, "welcomed": True}
        s.update(kw)
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(s, f)

    def start(self, *extra):
        env = dict(os.environ, YTT_DATA_DIR=self.data)
        self.proc = subprocess.Popen([self.exe, "--hidden", "--data-dir", self.data, "--autostart-key", r"Software\YTT-HoloColors-E2E"] + list(extra), env=env)
        self.wait("見えない受け口の窓", lambda: find_window(self.proc.pid, "HoloColors.Messages"), 10)
        self.main = self.wait("一覧の窓", lambda: find_window(self.proc.pid, TITLE), 10)

    def quit(self):
        if self.proc and self.proc.poll() is None:
            subprocess.run([self.exe, "--quit", "--data-dir", self.data], timeout=10)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                raise Failure("--quit で終わらない")

    def front_tk(self):
        """テストの窓を前面へ(Windows は、ほかのプロセスが前面を取るのを制限しているので Alt を押して解く)"""
        self.root.deiconify()
        self.root.lift()
        for attempt in range(5):
            if user32.GetForegroundWindow() == self.tk_hwnd:
                break
            press(VK["alt"])
            user32.SetForegroundWindow(self.tk_hwnd)
            self.pump(0.15)
        self.entry.focus_force()
        self.pump(0.1)
        return user32.GetForegroundWindow() == self.tk_hwnd

    def guard(self, hwnd, what):
        """キーを送る前に、前面がテストの窓か確かめる(他のアプリに文字や Enter を送らないため)"""
        if user32.GetForegroundWindow() != hwnd:
            raise Failure("前面の窓が変わったので止めました(%s)。テストの間はマウスとキーボードに触らないでください" % what)

    def visible(self):
        return bool(user32.IsWindowVisible(self.main))

    def pick_member(self):
        """ローマ字で検索すると1人だけ当たる人(その人が先頭に来る)。
        最初のグループ以外から選ぶ(検索しなくても先頭にいる人だと、絞り込めたかを確かめられないため)"""
        people = [(g, m) for g in self.members["groups"] for m in g["members"]]
        fold = lambda s: "".join((s or "").lower().split())
        for g, m in people:
            q = fold(m.get("en"))
            if g is self.members["groups"][0] or len(q) < 5:
                continue
            hay = [fold(x.get("en")) + "|" + fold(x.get("name")) + "|" + fold(x.get("note")) + "|" + fold(y["name"]) for y, x in people if x is not m]
            if not any(q in h for h in hay):
                return m, q
        raise Failure("検索で1人だけ当たる人がいない")

    def first_member(self):
        return self.members["groups"][0]["members"][0]

    def palette_child(self):
        best, area = None, 0
        for c in children(self.main):
            r = wintypes.RECT()
            user32.GetClientRect(c, ctypes.byref(r))
            if user32.IsWindowVisible(c) and r.right * r.bottom > area:
                best, area = c, r.right * r.bottom
        return best

    def status_text(self):
        for c in children(self.main):
            t = window_text(c)
            if t.startswith("コピー"):
                return t
        return ""

    # ---- 確かめること ----
    def run(self):
        self.write_settings()
        self.start()
        self.check(not self.visible(), "--hidden では一覧を出さない")
        have_front = self.front_tk()
        if not have_front:
            print("注意: テストの窓を前面にできなかったので、元の窓へ戻ることの確認は飛ばします")

        member, query = self.pick_member()
        hotkey()
        self.wait("キーで一覧が開く", self.visible)
        self.wait("一覧が前面に来る", lambda: user32.GetForegroundWindow() == self.main)
        self.check(True, "呼び出しのキーで一覧が開いて前面に来る")
        self.pump(0.2)
        self.guard(self.main, "検索の入力")
        type_text(query)
        self.pump(0.3)
        self.guard(self.main, "Enter")
        press(VK["enter"])
        self.wait("コピーしたら閉じる", lambda: not self.visible())
        self.check(get_clipboard() == member["hex"].upper(), "検索して Enter で色がコピーされる(%s %s)" % (member["name"], member["hex"]))
        if have_front:
            self.wait("元の窓へ戻る", lambda: user32.GetForegroundWindow() == self.tk_hwnd)
            self.check(True, "閉じたら呼び出す前の窓へ戻る")
            self.entry.delete(0, "end")
            self.entry.focus_force()
            self.pump(0.1)
            self.guard(self.tk_hwnd, "貼り付け")
            press(VK["ctrl"], VK["v"])
            self.wait("貼り付け", lambda: self.entry.get() == member["hex"].upper())
            self.check(True, "そのまま Ctrl+V で貼り付けられる")

        # キーをもう一度押すと閉じる / Esc で閉じる
        hotkey()
        self.wait("開く", lambda: self.visible() and user32.GetForegroundWindow() == self.main)
        hotkey()
        self.wait("もう一度のキーで閉じる", lambda: not self.visible())
        self.check(True, "開いているときにキーをもう一度押すと閉じる")
        hotkey()
        self.wait("開く", lambda: self.visible() and user32.GetForegroundWindow() == self.main)
        self.guard(self.main, "Esc")
        press(VK["esc"])
        self.wait("Esc で閉じる", lambda: not self.visible())
        self.check(True, "Esc で閉じる")

        # 札のクリックでコピー(検索は開くたびに空に戻る → 先頭の札は1つ目のグループの1人目)
        hotkey()
        self.wait("開く", lambda: self.visible() and user32.GetForegroundWindow() == self.main)
        self.pump(0.3)
        pal = self.palette_child()
        k = user32.GetDpiForWindow(self.main) / 96.0
        pt = wintypes.POINT(int(12 * k + 30 * k), int((4 + 28 + 23) * k))
        user32.ClientToScreen(pal, ctypes.byref(pt))
        set_clipboard("before")
        user32.WindowFromPoint.argtypes = (wintypes.POINT,)
        user32.WindowFromPoint.restype = wintypes.HWND
        if user32.GetAncestor(user32.WindowFromPoint(pt), 2) != self.main:
            raise Failure("クリックする場所に一覧の窓が無いので止めました")
        self.guard(self.main, "クリック")
        click(pt.x, pt.y)
        self.wait("クリックで閉じる", lambda: not self.visible())
        first = self.first_member()
        self.check(get_clipboard() == first["hex"].upper(), "札のクリックで色がコピーされる(%s %s)" % (first["name"], first["hex"]))

        # 2つ目の起動は、動いているほうの一覧を出して終わる
        r = subprocess.run([self.exe, "--data-dir", self.data], timeout=10)
        self.check(r.returncode == 0, "2つ目の起動はすぐ終わる")
        self.wait("動いているほうが開く", self.visible)
        self.check(self.proc.poll() is None, "動いているほうはそのまま")
        self.wait("前面", lambda: user32.GetForegroundWindow() == self.main)
        self.guard(self.main, "Esc")
        press(VK["esc"])
        self.wait("閉じる", lambda: not self.visible())
        self.quit()
        self.check(self.proc.returncode == 0, "--quit で終わる")

        # 閉じない設定・# なし
        self.write_settings(closeAfterCopy=False, includeHash=False)
        self.start()
        self.front_tk()
        hotkey()
        self.wait("開く", lambda: self.visible() and user32.GetForegroundWindow() == self.main)
        self.pump(0.2)
        self.guard(self.main, "検索の入力")
        type_text(query)
        self.pump(0.3)
        self.guard(self.main, "Enter")
        press(VK["enter"])
        want = member["hex"].upper().lstrip("#")
        self.wait("コピー", lambda: get_clipboard() == want)
        self.pump(0.3)
        self.check(self.visible(), "「コピーしたら閉じる」を外すと開いたまま")
        self.check(get_clipboard() == want, "# を付けない設定では 16 進数だけ(%s)" % want)
        self.check(member["name"] in self.status_text(), "何をコピーしたか下に出る: " + self.status_text())
        self.quit()

        log = os.path.join(self.data, "holo-colors.log")
        text = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
        self.check("error:" not in text, "ログにエラーが無い")


def main():
    if sys.platform != "win32":
        print("Windows だけのテストです")
        return 0
    if not os.path.exists(os.path.join(BUILD, "HoloColors.exe")):
        print("先に holo-colors/build.bat を流してください")
        return 1
    saved = get_clipboard()
    t = E2E()
    try:
        t.run()
        print("\nOK: %d 件" % t.passed)
        return 0
    except Failure as e:
        print("\nFAIL:", e, "(成功 %d 件)" % t.passed)
        return 1
    finally:
        try:
            t.quit()
        except Exception as e:   # 後始末の失敗で本来の結果を隠さない
            print("後始末:", e)
        t.root.destroy()
        set_clipboard(saved)
        shutil.rmtree(t.tmp, ignore_errors=True)
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\YTT-HoloColors-E2E")
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
