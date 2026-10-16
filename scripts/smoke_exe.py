"""Check a built executable's window and clean shutdown without drawing."""

import argparse
import ctypes
import json
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab, ImageStat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    arguments = parser.parse_args()
    executable = arguments.executable.resolve(strict=True)
    output = Path(__file__).resolve().parents[1] / "test_artifacts"
    output.mkdir(exist_ok=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM,
                                          wintypes.UINT, wintypes.UINT,
                                          ctypes.POINTER(ctypes.c_size_t)]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                   wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.SetProcessDPIAware()

    def windows():
        found = []

        @callback_type
        def inspect(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = kernel32.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return True
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(buffer))
                if (kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length))
                        and Path(buffer.value) == executable):
                    title = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, title, len(title))
                    found.append((hwnd, title.value, pid.value))
            finally:
                kernel32.CloseHandle(handle)
            return True

        user32.EnumWindows(inspect, 0)
        return found

    if windows():
        raise SystemExit("Close the existing instance of this executable before testing.")
    environment = os.environ.copy()
    for name in ("CHENGHUA_API_KEY", "SILICONFLOW_API_KEY", "CHENGHUA_BASE_URL"):
        environment.pop(name, None)
    started = time.monotonic()
    process = subprocess.Popen([str(executable)], cwd=executable.parent, env=environment)
    hwnd = None
    try:
        deadline = started + 45
        while time.monotonic() < deadline:
            candidates = windows()
            for candidate, title, pid in candidates:
                if title == "\u57ce\u753b \u00b7 \u81ea\u52a8\u7ed8\u753b":
                    hwnd = candidate
                    break
            if hwnd:
                break
            if process.poll() is not None:
                raise RuntimeError(f"Executable exited before opening its window: {process.returncode}")
            time.sleep(0.2)
        if not hwnd:
            raise RuntimeError(f"No application window appeared: {windows()}")
        startup_seconds = time.monotonic() - started
        result = ctypes.c_size_t()
        if not user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 2, 3000, ctypes.byref(result)):
            raise RuntimeError("Application window did not respond.")
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.8)
        rectangle = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
            raise ctypes.WinError(ctypes.get_last_error())
        image = ImageGrab.grab(bbox=(rectangle.left, rectangle.top,
                                    rectangle.right, rectangle.bottom), all_screens=True)
        if image.width < 900 or image.height < 600 or max(ImageStat.Stat(image).stddev) < 10:
            raise RuntimeError("Application screenshot is blank or incorrectly sized.")
        screenshot = output / "release_exe.png"
        image.save(screenshot)
        log = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) \
            / "Chenghua" / "chenghua_debug.log"
        if not log.is_file():
            raise RuntimeError("Persistent log file was not created.")
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
        code = process.wait(timeout=15)
        if code != 0:
            raise RuntimeError(f"Executable exited with code {code}")
        report = {"executable": str(executable), "title": title,
                  "startup_seconds": round(startup_seconds, 3), "exit_code": code,
                  "screenshot": str(screenshot), "persistent_log": str(log),
                  "window_size": list(image.size)}
        (output / "release_smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
    finally:
        if process.poll() is None:
            for window, _, _ in windows():
                user32.PostMessageW(window, 0x0010, 0, 0)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
