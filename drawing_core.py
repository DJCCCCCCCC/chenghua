from __future__ import annotations

import ctypes
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterator, List, Sequence, Tuple, Union


Point = Tuple[int, int]
Stroke = List[Point]
Area = Tuple[int, int, int, int]


def enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    try:
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_bool
        if setter(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    user32.SetProcessDPIAware()


def desktop_bounds() -> Area:
    if os.name != "nt":
        raise OSError("Mouse drawing requires Windows")
    metrics = ctypes.windll.user32.GetSystemMetrics
    return tuple(int(metrics(index)) for index in (76, 77, 78, 79))


def validate_area(area: Area, bounds: Area) -> None:
    x, y, width, height = area
    left, top, screen_width, screen_height = bounds
    if width < 11 or height < 11:
        raise ValueError("Canvas width and height must exceed 10 pixels")
    if x < left or y < top or x + width > left + screen_width or y + height > top + screen_height:
        raise ValueError("Canvas must be inside the virtual desktop")


def fit_area(image_size: Tuple[int, int], area: Area, keep_aspect: bool = False) -> Area:
    iw, ih = image_size
    x, y, width, height = area
    if min(iw, ih, width, height) <= 0:
        raise ValueError("Image and canvas dimensions must be positive")
    if keep_aspect:
        scale = min(width / iw, height / ih)
        fitted_w, fitted_h = max(1, round(iw * scale)), max(1, round(ih * scale))
        x += (width - fitted_w) // 2
        y += (height - fitted_h) // 2
        width, height = fitted_w, fitted_h
    return x, y, width, height


def map_stroke(points: Sequence[Point], image_size: Tuple[int, int], area: Area) -> Stroke:
    iw, ih = image_size
    x0, y0, width, height = area
    if min(iw, ih, width, height) <= 0:
        raise ValueError("Image and canvas dimensions must be positive")
    # Match DrawingThread's width/image_width formula, with an edge safety clamp.
    return [
        (x0 + min(width - 1, max(0, round(float(x) * width / iw))),
         y0 + min(height - 1, max(0, round(float(y) * height / ih))))
        for x, y in points
    ]


def interpolate(start: Point, end: Point, max_step: int) -> Iterator[Point]:
    if max_step < 1:
        raise ValueError("Interpolation step must be positive")
    steps = max(1, math.ceil(math.hypot(end[0] - start[0], end[1] - start[1]) / max_step))
    previous = start
    for index in range(1, steps + 1):
        point = (round(start[0] + (end[0] - start[0]) * index / steps),
                 round(start[1] + (end[1] - start[1]) * index / steps))
        if point != previous:
            yield point
            previous = point


@dataclass(frozen=True)
class DrawingConfig:
    area: Area
    image_size: Tuple[int, int]
    speed: float = 0.0001
    max_step: int = 5
    countdown: int = 3
    extra_delay: float = 0.005
    lift_delay: float = 0.15
    right_button: bool = False
    keep_aspect: bool = False

    def validate(self, bounds: Area) -> None:
        validate_area(self.area, bounds)
        if min(self.image_size) <= 0 or self.max_step < 1 or self.countdown < 0:
            raise ValueError("Invalid image size, step or countdown")
        if any(not math.isfinite(v) or v < 0 for v in (self.speed, self.extra_delay, self.lift_delay)):
            raise ValueError("Delays must be finite nonnegative numbers")

    @property
    def target_area(self) -> Area:
        return fit_area(self.image_size, self.area, self.keep_aspect)


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32), ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t),
    ]


class KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", ctypes.c_uint32), ("data", InputUnion)]


class Win32MouseBackend:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Mouse drawing requires Windows")
        self.user32 = ctypes.windll.user32
        self.user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(Input), ctypes.c_int]
        self.user32.SendInput.restype = ctypes.c_uint
        self.bounds = desktop_bounds()

    def _send(self, flags: int, x: int = 0, y: int = 0) -> None:
        event = Input(type=0, mi=MouseInput(dx=x, dy=y, dwFlags=flags))
        if self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
            raise OSError("Windows 拒绝鼠标输入，请检查目标窗口是否以更高权限运行。")

    def move(self, x: int, y: int) -> None:
        left, top, width, height = self.bounds
        if not (left <= x < left + width and top <= y < top + height):
            raise ValueError("Mouse destination is outside the desktop")
        nx = round((x - left) * 65535 / max(1, width - 1))
        ny = round((y - top) * 65535 / max(1, height - 1))
        self._send(0x0001 | 0x2000 | 0x8000 | 0x4000, nx, ny)

    def button(self, down: bool, right: bool) -> None:
        flags = (0x0008 if down else 0x0010) if right else (0x0002 if down else 0x0004)
        self._send(flags)


class WindowsMouseController:
    """Single drawing worker, with synchronous and idempotent pen release."""

    def __init__(self, backend=None) -> None:
        self.backend = backend if backend is not None else Win32MouseBackend()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._lock = threading.RLock()
        self._held = False
        self._right = False

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def _release_locked(self) -> None:
        if self._held:
            self._held = False
            self.backend.button(False, self._right)

    def release(self) -> None:
        with self._lock:
            self._release_locked()

    def reset_stop(self) -> None:
        with self._lock:
            self._release_locked()
            self._stop.clear()
            self._paused.clear()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            self._paused.clear()
            self._release_locked()

    def pause(self) -> None:
        with self._lock:
            self._paused.set()
            self._release_locked()

    def resume(self) -> None:
        self._paused.clear()

    def wait(self, seconds: float) -> bool:
        if seconds <= 0:
            return not self.stopped
        return not self._stop.wait(max(0.0, seconds))

    def wait_until_resumed(self) -> bool:
        while self.paused and not self.stopped:
            self._stop.wait(0.02)
        return not self.stopped

    def _begin(self, point: Point, right: bool, lift_delay: float, rapid: Callable[[], bool]) -> bool:
        while self.wait_until_resumed():
            with self._lock:
                if self.stopped:
                    return False
                if self.paused:
                    continue
                self.backend.move(*point)
            if not self.wait(0 if rapid() else (lift_delay if lift_delay > 0 else 0.05)):
                return False
            with self._lock:
                if self.stopped:
                    return False
                if self.paused:
                    continue
                # The user may have moved the cursor while paused.
                self.backend.move(*point)
                self._right = right
                self._held = True
                self.backend.button(True, right)
            return self.wait(0 if rapid() else 0.02)
        return False

    def draw_stroke(
        self, points: Sequence[Point], delay: Union[float, Callable[[], float]] = 0.0051, max_step: int = 5,
        right_button: bool = False, lift_delay: float = 0.15,
        rapid: Callable[[], bool] = lambda: False,
    ) -> bool:
        if self.stopped:
            return False
        if len(points) < 2:
            return True
        last = points[0]
        rapid_moves = 0
        try:
            if not self._begin(last, right_button, lift_delay, rapid):
                return False
            for start, end in zip(points, points[1:]):
                for point in interpolate(start, end, max_step):
                    while True:
                        if not self.wait_until_resumed():
                            return False
                        if not self._held and not self._begin(last, right_button, lift_delay, rapid):
                            return False
                        with self._lock:
                            if self.stopped:
                                return False
                            if self.paused or not self._held:
                                continue
                            self.backend.move(*point)
                            last = point
                            break
                    point_delay = delay() if callable(delay) else delay
                    if not math.isfinite(point_delay) or point_delay < 0:
                        raise ValueError("Point delay must be finite and nonnegative")
                    if not self.wait(point_delay):
                        return False
                    if point_delay == 0:
                        rapid_moves += 1
                        if rapid_moves % 64 == 0:
                            # Yield in bounded batches so cancellation and the target can run.
                            time.sleep(0)
            return not self.stopped
        finally:
            self.release()
            self.wait(0 if rapid() else 0.03)
