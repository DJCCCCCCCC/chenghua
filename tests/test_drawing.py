import json
import ctypes
import math
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from PIL import Image, ImageDraw

from drawing_core import (
    DrawingConfig, Input, Win32MouseBackend, WindowsMouseController,
    fit_area, interpolate, map_stroke, validate_area,
)
from image_processing import ImageProcessor, render_strokes


class RecordingBackend:
    def __init__(self):
        self.events = []
        self.held = False
        self.position = None
        self.on_move = None
        self.on_button = None

    def move(self, x, y):
        self.position = (x, y)
        self.events.append(("move", x, y, self.held))
        if self.on_move:
            self.on_move(x, y)

    def button(self, down, right):
        self.held = down
        self.events.append(("down" if down else "up", right))
        if self.on_button:
            self.on_button(down, right)


class CoordinateTests(unittest.TestCase):
    def test_original_scaling_and_edge_clamp(self):
        self.assertEqual(map_stroke([(0, 0), (50, 25), (99, 49)], (100, 50), (10, 20, 200, 100)),
                         [(10, 20), (110, 70), (208, 118)])
        self.assertEqual(map_stroke([(99, 49), (100, 50), (-3, -5)], (100, 50), (0, 0, 10, 10)),
                         [(9, 9), (9, 9), (0, 0)])

    def test_aspect_fit_and_default_stretch(self):
        self.assertEqual(fit_area((200, 100), (10, 20, 100, 100)), (10, 20, 100, 100))
        self.assertEqual(fit_area((200, 100), (10, 20, 100, 100), True), (10, 45, 100, 50))

    def test_negative_monitor_coordinates(self):
        validate_area((-1900, 20, 500, 300), (-1920, 0, 3840, 1080))
        self.assertEqual(map_stroke([(0, 0)], (100, 100), (-1900, 20, 500, 300)), [(-1900, 20)])

    def test_invalid_canvas_is_rejected(self):
        for area in [(0, 0, 0, 20), (0, 0, 20, 10), (-1, 0, 40, 40), (990, 0, 20, 20)]:
            with self.subTest(area=area), self.assertRaises(ValueError):
                validate_area(area, (0, 0, 1000, 800))

    def test_invalid_delays_and_settings_are_rejected(self):
        base = DrawingConfig((10, 10, 400, 300), (200, 100))
        base.validate((0, 0, 1000, 800))
        for changes in ({"speed": math.nan}, {"extra_delay": math.inf}, {"lift_delay": -1},
                        {"max_step": 0}, {"countdown": -1}, {"image_size": (0, 50)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(base, **changes).validate((0, 0, 1000, 800))

    def test_interpolation_reaches_endpoint_without_duplicates(self):
        points = list(interpolate((0, 0), (27, 11), 5))
        self.assertEqual(points[-1], (27, 11))
        self.assertEqual(len(points), len(set(points)))
        for start, end in zip([(0, 0)] + points, points):
            self.assertLessEqual(math.dist(start, end), 5 + math.sqrt(2))
        self.assertEqual(list(interpolate((2, 2), (2, 2), 5)), [])
        with self.assertRaises(ValueError):
            list(interpolate((0, 0), (1, 1), 0))


class Win32BackendTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        def record_input(count, pointer, size):
            self.assertEqual(count, 1)
            self.assertEqual(size, 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
            event = ctypes.cast(pointer, ctypes.POINTER(Input)).contents
            self.assertEqual(event.type, 0)
            self.events.append((event.mi.dwFlags, event.mi.dx, event.mi.dy))
            return 1
        self.api = mock.Mock(side_effect=record_input)
        self.patches = [
            mock.patch("drawing_core.ctypes.windll.user32.SendInput", self.api),
            mock.patch("drawing_core.desktop_bounds", return_value=(-1920, 0, 3840, 1080)),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.backend = Win32MouseBackend()

    def test_virtual_desktop_absolute_coordinates(self):
        self.backend.move(-1920, 0)
        self.assertEqual(self.events[-1], (0xE001, 0, 0))
        self.backend.move(1919, 1079)
        self.assertEqual(self.events[-1], (0xE001, 65535, 65535))

    def test_outside_desktop_never_calls_windows(self):
        with self.assertRaises(ValueError):
            self.backend.move(1920, 1080)
        self.api.assert_not_called()

    def test_exact_left_and_right_button_flags(self):
        for down, right, flag in [(True, False, 2), (False, False, 4),
                                  (True, True, 8), (False, True, 16)]:
            self.backend.button(down, right)
            self.assertEqual(self.events[-1], (flag, 0, 0))

    def test_rejected_input_reports_failure(self):
        self.api.side_effect = None
        self.api.return_value = 0
        with self.assertRaisesRegex(OSError, "Windows"):
            self.backend.move(0, 0)


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fixture.png"
        image = Image.new("RGB", (240, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((20, 20, 100, 100), outline="black", width=3)
        draw.rectangle((145, 70, 215, 150), outline="black", width=3)
        image.save(self.path)

    def test_canny_produces_contiguous_paths_not_cross_shape_jumps(self):
        processor = ImageProcessor(self.path)
        processor.preprocess(3, 50, 150)
        strokes = processor.extract_strokes(15)
        self.assertGreater(len(strokes), 1)
        for stroke in strokes:
            for a, b in zip(stroke, stroke[1:]):
                self.assertLessEqual(math.dist(a, b), math.sqrt(2) + 1e-9)
            # The separate objects must never be joined into one drag.
            xs = [p[0] for p in stroke]
            self.assertFalse(min(xs) < 110 and max(xs) > 130)

    def test_human_order_and_json_native_integers(self):
        processor = ImageProcessor(self.path)
        strokes = processor.extract_strokes(10)
        starts = [(stroke[0][1], stroke[0][0]) for stroke in strokes]
        self.assertEqual(starts, sorted(starts))
        for stroke in strokes:
            self.assertTrue(all(type(x) is int and type(y) is int for x, y in stroke))
        self.assertEqual(len(json.loads(json.dumps(strokes))), len(strokes))

    def test_non_human_order_is_longest_first(self):
        processor = ImageProcessor(self.path)
        lengths = list(map(len, processor.extract_strokes(10, human_order=False)))
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_simplify_retains_endpoints_and_reduces_points(self):
        processor = ImageProcessor(self.path)
        before = [list(stroke) for stroke in processor.extract_strokes(10)]
        after = processor.sharpen_strokes(10)
        self.assertLess(sum(map(len, after)), sum(map(len, before)))
        self.assertEqual([(s[0], s[-1]) for s in before], [(s[0], s[-1]) for s in after])

    def test_preview_uses_actual_strokes(self):
        processor = ImageProcessor(self.path)
        processor.processed = True
        processor.strokes = [[(10, 10), (20, 10)]]
        preview = processor.preview()
        self.assertEqual(preview.getpixel((15, 10)), (0, 0, 0))
        self.assertEqual(preview.getpixel((145, 70)), (255, 255, 255))

    def test_transparency_and_blank_image(self):
        Image.new("RGBA", (120, 120), (0, 0, 0, 0)).save(self.path)
        processor = ImageProcessor(self.path)
        self.assertEqual(processor.original.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(processor.extract_strokes(), [])
        self.assertTrue(processor.processed)

    def test_rendered_target_obeys_aspect_option(self):
        strokes = [[(0, 0), (99, 49)]]
        image = render_strokes(strokes, (100, 50), (200, 200), keep_aspect=True)
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(image.getpixel((0, 50)), (0, 0, 0))
        overlay = render_strokes(strokes, (100, 50), (200, 200), transparent=True)
        self.assertEqual(overlay.getpixel((0, 0)), (20, 220, 90, 255))
        self.assertEqual(overlay.getpixel((100, 0))[3], 0)


class MouseControllerTests(unittest.TestCase):
    def setUp(self):
        self.backend = RecordingBackend()
        self.mouse = WindowsMouseController(self.backend)
        self.workers = []
        self.addCleanup(self.cleanup_workers)

    def cleanup_workers(self):
        self.mouse.stop()
        for worker in self.workers:
            worker.join(2)
            self.assertFalse(worker.is_alive(), "drawing worker did not stop")

    def run_async(self, points, **kwargs):
        self.results = []
        worker = threading.Thread(target=lambda: self.results.append(
            self.mouse.draw_stroke(points, delay=0, lift_delay=0.001, **kwargs)), daemon=True)
        self.workers.append(worker)
        worker.start()
        return worker

    def test_order_and_button_release(self):
        self.assertTrue(self.mouse.draw_stroke([(0, 0), (20, 0)], 0, 5, lift_delay=0.001))
        self.assertEqual(self.backend.events[0], ("move", 0, 0, False))
        self.assertEqual([e for e in self.backend.events if e[0] != "move"], [("down", False), ("up", False)])
        self.assertEqual([e[1:3] for e in self.backend.events if e[0] == "move" and e[3]],
                         [(5, 0), (10, 0), (15, 0), (20, 0)])

    def test_right_button_pair(self):
        self.mouse.draw_stroke([(10, 10), (20, 20)], 0, right_button=True, lift_delay=0.001)
        self.assertEqual([e for e in self.backend.events if e[0] != "move"], [("down", True), ("up", True)])

    def test_stop_before_start_has_no_events(self):
        self.mouse.stop()
        self.assertFalse(self.mouse.draw_stroke([(0, 0), (20, 0)]))
        self.assertEqual(self.backend.events, [])

    def test_stop_during_lift_never_presses(self):
        self.backend.on_move = lambda x, y: self.mouse.stop()
        self.assertFalse(self.mouse.draw_stroke([(0, 0), (20, 0)], lift_delay=1))
        self.assertFalse(any(e[0] == "down" for e in self.backend.events))

    def test_stop_during_interpolation_releases_immediately(self):
        def stop_at(x, y):
            if x >= 10:
                self.mouse.stop()
        self.backend.on_move = stop_at
        self.assertFalse(self.mouse.draw_stroke([(0, 0), (100, 0)], 0, 5, lift_delay=0.001))
        self.assertEqual(self.backend.position, (10, 0))
        self.assertEqual(self.backend.events[-1], ("up", False))
        self.assertFalse(self.backend.held)

    def test_pause_releases_and_resume_repositions_without_bridge(self):
        paused = threading.Event()
        def pause_at(x, y):
            if (x, y) == (10, 0) and not paused.is_set():
                self.mouse.pause()
                paused.set()
        self.backend.on_move = pause_at
        worker = self.run_async([(0, 0), (30, 0)], max_step=5)
        self.assertTrue(paused.wait(1))
        self.assertFalse(self.backend.held)
        count = len(self.backend.events)
        time.sleep(0.06)
        self.assertEqual(len(self.backend.events), count)
        self.backend.position = (900, 900)
        self.mouse.resume()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.results, [True])
        resumed = self.backend.events[count:]
        self.assertEqual(resumed[0], ("move", 10, 0, False))
        self.assertEqual(self.backend.position, (30, 0))
        self.assertEqual([e[0] for e in resumed if e[0] != "move"], ["down", "up"])

    def test_stop_while_paused_unblocks_worker(self):
        paused = threading.Event()
        def pause_at(x, y):
            if x == 5:
                self.mouse.pause()
                paused.set()
        self.backend.on_move = pause_at
        worker = self.run_async([(0, 0), (100, 0)], max_step=5)
        self.assertTrue(paused.wait(1))
        self.mouse.stop()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.results, [False])
        self.assertFalse(self.backend.held)

    def test_stop_interrupts_long_wait(self):
        result = []
        worker = threading.Thread(target=lambda: result.append(self.mouse.wait(60)), daemon=True)
        self.workers.append(worker)
        worker.start()
        self.mouse.stop()
        worker.join(0.5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])

    def test_exception_after_press_releases_button(self):
        def fail_move(x, y):
            if self.backend.held:
                raise RuntimeError("simulated backend failure")
        self.backend.on_move = fail_move
        with self.assertRaisesRegex(RuntimeError, "simulated"):
            self.mouse.draw_stroke([(0, 0), (20, 0)], 0, lift_delay=0.001)
        self.assertEqual(self.backend.events[-1], ("up", False))
        self.assertFalse(self.backend.held)

    def test_release_is_idempotent(self):
        self.mouse.draw_stroke([(0, 0), (10, 0)], 0, lift_delay=0.001)
        count = len(self.backend.events)
        self.mouse.release()
        self.mouse.stop()
        self.assertEqual(len(self.backend.events), count)

    def test_delay_provider_is_read_for_each_point(self):
        provider = mock.Mock(side_effect=[0, 0.001, 0.002, 0])
        with mock.patch.object(self.mouse, "wait", return_value=True) as wait:
            self.assertTrue(self.mouse.draw_stroke([(0, 0), (20, 0)], provider, 5, lift_delay=0.001))
        self.assertEqual(provider.call_count, 4)
        delays = [call.args[0] for call in wait.call_args_list]
        self.assertEqual(delays[2:6], [0, 0.001, 0.002, 0])

    def test_rapid_mode_removes_all_fixed_waits_without_skipping_points(self):
        with mock.patch.object(self.mouse, "wait", return_value=True) as wait:
            self.assertTrue(self.mouse.draw_stroke([(0, 0), (20, 0)], 0, 5,
                                                   lift_delay=0.15, rapid=lambda: True))
        self.assertTrue(all(call.args[0] == 0 for call in wait.call_args_list))
        self.assertEqual([event[1:3] for event in self.backend.events if event[0] == "move" and event[3]],
                         [(5, 0), (10, 0), (15, 0), (20, 0)])
        self.assertEqual(self.backend.events[-1], ("up", False))

    def test_rapid_mode_cancellation_still_releases_immediately(self):
        self.backend.on_move = lambda x, y: self.mouse.stop() if x >= 10 else None
        self.assertFalse(self.mouse.draw_stroke([(0, 0), (100, 0)], 0, 5, rapid=lambda: True))
        self.assertEqual(self.backend.position, (10, 0))
        self.assertEqual(self.backend.events[-1], ("up", False))

    def test_speed_can_leave_rapid_mode_mid_stroke(self):
        live_delay = [0.0]
        def slow_down(x, y):
            if x >= 10:
                live_delay[0] = 0.005
        self.backend.on_move = slow_down
        with mock.patch.object(self.mouse, "wait", return_value=True) as wait:
            self.mouse.draw_stroke([(0, 0), (20, 0)], lambda: live_delay[0], 5,
                                   rapid=lambda: live_delay[0] == 0)
        self.assertIn(mock.call(0.005), wait.call_args_list)
        self.assertEqual(wait.call_args_list[-1], mock.call(0.03))

    def test_reset_allows_new_run_after_stop(self):
        self.mouse.stop()
        self.mouse.reset_stop()
        self.assertTrue(self.mouse.draw_stroke([(0, 0), (10, 0)], 0, lift_delay=0.001))


if __name__ == "__main__":
    unittest.main()
