import sys
import ctypes
from ctypes import wintypes
import winreg
from PyQt6 import QtWidgets

user32 = ctypes.windll.user32

WM_INPUT = 0x00FF
RIM_TYPEKEYBOARD = 1
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007

# --- 構造体 ---
class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]

class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER)]

class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]

# --- デバイス名取得 ---
def get_device_name(hDevice):
    size = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, None, ctypes.byref(size))
    buf = ctypes.create_unicode_buffer(size.value)
    user32.GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, buf, ctypes.byref(size))
    return buf.value

# --- ★修正済：GUID除去 ---
def format_device_path(raw_path):
    path = raw_path.replace("\\\\?\\", "").replace("#", "\\").upper()

    if "\\{" in path:
        path = path.split("\\{")[0]

    return path.rstrip("\\")

# --- レジストリ書き込み ---
def write_registry(device_path, is_jis):
    reg_path = fr"SYSTEM\CurrentControlSet\Enum\{device_path}\Device Parameters"

    if is_jis:
        values = {
            "KeyboardTypeOverride": 7,
            "KeyboardSubtypeOverride": 2,
            "OverrideKeyboardType": 7,
            "OverrideKeyboardSubtype": 2,
        }
    else:
        values = {
            "KeyboardTypeOverride": 4,
            "KeyboardSubtypeOverride": 0,
            "OverrideKeyboardType": 4,
            "OverrideKeyboardSubtype": 0,
        }

    key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, reg_path, 0, winreg.KEY_SET_VALUE)

    for k, v in values.items():
        winreg.SetValueEx(key, k, 0, winreg.REG_DWORD, v)

    winreg.CloseKey(key)

# --- レジストリ読み取り（完全版） ---
def read_registry(device_path):
    reg_path = fr"SYSTEM\CurrentControlSet\Enum\{device_path}\Device Parameters"

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path, 0, winreg.KEY_READ)

        def get_val(name):
            try:
                return winreg.QueryValueEx(key, name)[0]
            except FileNotFoundError:
                return None

        t1 = get_val("KeyboardTypeOverride")
        s1 = get_val("KeyboardSubtypeOverride")
        t2 = get_val("OverrideKeyboardType")
        s2 = get_val("OverrideKeyboardSubtype")

        winreg.CloseKey(key)

        t = t2 if t2 is not None else t1
        s = s2 if s2 is not None else s1

        if t == 7 and s == 2:
            return "JIS"
        elif t == 4 and s == 0:
            return "US"
        elif t is None and s is None:
            return "未設定"
        else:
            return f"不明 (Type={t}, Subtype={s})"

    except FileNotFoundError:
        return "未設定"

# --- GUI ---
class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Keyboard Layout Setter")
        self.resize(640, 300)

        self.detecting = False
        self.device_path = None

        # UI
        self.info = QtWidgets.QLabel("識別ボタンを押してキー入力してください")
        self.path_display = QtWidgets.QLineEdit()
        self.path_display.setReadOnly(True)

        self.detect_btn = QtWidgets.QPushButton("キーボード識別開始")
        self.detect_btn.clicked.connect(self.start_detect)

        self.layout_select = QtWidgets.QComboBox()
        self.layout_select.addItems(["US", "JIS"])

        self.read_btn = QtWidgets.QPushButton("現在設定確認")
        self.read_btn.clicked.connect(self.read_action)

        self.write_btn = QtWidgets.QPushButton("レジストリ書き込み")
        self.write_btn.clicked.connect(self.write_action)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addWidget(self.read_btn)
        btn_layout.addWidget(self.write_btn)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.info)
        layout.addWidget(self.detect_btn)
        layout.addWidget(self.path_display)
        layout.addWidget(self.layout_select)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

        self.register_raw_input()

    def register_raw_input(self):
        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01
        rid.usUsage = 0x06
        rid.dwFlags = 0x00000100
        rid.hwndTarget = int(self.winId())

        if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid)):
            raise RuntimeError("Raw Input登録失敗")

    def start_detect(self):
        self.detecting = True
        self.info.setText("対象キーボードでキーを1回押してください")

    def nativeEvent(self, eventType, message):
        msg = ctypes.wintypes.MSG.from_address(message.__int__())

        if msg.message == WM_INPUT:
            self.handle_input(msg.lParam)

        return False, 0

    def handle_input(self, lparam):
        if not self.detecting:
            return

        size = wintypes.UINT(0)
        user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))

        buffer = ctypes.create_string_buffer(size.value)
        user32.GetRawInputData(lparam, RID_INPUT, buffer, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))

        raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents

        if raw.header.dwType == RIM_TYPEKEYBOARD:
            raw_name = get_device_name(raw.header.hDevice)
            self.device_path = format_device_path(raw_name)

            self.path_display.setText(self.device_path)
            self.info.setText("識別完了")
            self.detecting = False

    def read_action(self):
        if not self.device_path:
            self.info.setText("先に識別してください")
            return

        result = read_registry(self.device_path)
        self.info.setText(f"現在設定: {result}")

    def write_action(self):
        if not self.device_path:
            self.info.setText("先に識別してください")
            return

        is_jis = self.layout_select.currentText() == "JIS"

        try:
            write_registry(self.device_path, is_jis)
            self.info.setText("書き込み完了（再接続または再起動必要）")
        except PermissionError:
            self.info.setText("管理者権限で実行してください")

# --- 実行 ---
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())