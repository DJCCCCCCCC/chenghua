import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw, ImageGrab

from canvas_selector import CanvasSelector
from drawing_core import DrawingConfig, WindowsMouseController, desktop_bounds, interpolate, map_stroke
from image_processing import render_strokes
from test_drawing import RecordingBackend
from chenghua_app import App


OUTPUT = Path(__file__).resolve().parents[1] / "test_artifacts"


def make_fixture(path):
    image = Image.new("RGB", (640, 480), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(140, 235), (315, 85), (490, 235)], fill="black", width=5)
    draw.rectangle((170, 235, 460, 400), outline="black", width=5)
    draw.rectangle((285, 290, 350, 400), outline="black", width=4)
    draw.rectangle((200, 265, 255, 320), outline="black", width=4)
    draw.line((200, 292, 255, 292), fill="black", width=3)
    draw.line((227, 265, 227, 320), fill="black", width=3)
    draw.ellipse((495, 55, 565, 125), outline="black", width=4)
    draw.line((90, 404, 545, 404), fill="black", width=3)
    image.save(path)


class RasterBackend(RecordingBackend):
    def __init__(self, size):
        super().__init__()
        self.image = Image.new("RGB", size, "white")
        self.draw = ImageDraw.Draw(self.image)

    def move(self, x, y):
        if self.held and self.position is not None:
            self.draw.line([self.position, (x, y)], fill="black", width=1)
        super().move(x, y)


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUTPUT.mkdir(exist_ok=True)
        cls.fixture = OUTPUT / "sample_input.png"
        make_fixture(cls.fixture)
        cls.backend = RecordingBackend()
        cls.app = App(WindowsMouseController(cls.backend))
        cls.app.withdraw()
        cls.callback_errors = []
        cls.app.report_callback_exception = lambda *args: cls.callback_errors.append(str(args[1]))
        # Never interpret the user's physical keypresses during an automated test.
        cls.key_patcher = mock.patch.object(cls.app, "_poll_keys")
        cls.key_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.app._close()
        cls.key_patcher.stop()

    def setUp(self):
        self.errors = []
        self.error_patcher = mock.patch("chenghua_app.messagebox.showerror",
                                       side_effect=lambda title, text, **kw: self.errors.append((title, text)))
        self.error_patcher.start()
        self.addCleanup(self.error_patcher.stop)
        self.app.mouse.reset_stop()
        self.backend.events.clear()
        self.app._paint()
        self.app.api_key.set("")
        self.app.base_url.set("https://api.openai.com/v1")
        self.app.prompt.set("")
        self.app._load_image(self.fixture)
        self.app.withdraw()
        for var in self.app.area_vars:
            var.set(0)
        self.app._keys_down.clear()
        self.app.countdown.set(3)
        self.app.speed.set(0.005)
        self.app.lift_delay.set(150)

    def pump_until(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail("GUI timed out waiting for condition")

    def process_image(self):
        self.app._process_image()
        self.pump_until(lambda: not self.app._processing)
        self.assertGreater(len(self.app.processor.strokes), 0)
        self.assertEqual(self.errors, [])

    def tearDown(self):
        if self.app._drawing:
            self.app._stop_drawing()
            self.pump_until(lambda: not self.app._drawing)
        self.app.withdraw()
        self.assertEqual(self.callback_errors, [])

    def test_processing_ui_and_resampling_preview(self):
        self.process_image()
        self.app.deiconify()
        self.app.update()
        self.app._refresh_preview()
        self.assertIsNotNone(self.app.preview_photo)
        self.assertEqual(str(self.app.start_button["state"]), "normal")
        self.assertEqual(self.app.progress.get(), 100)
        self.assertIn("pbar", self.app.progress_bar.identify(self.app.progress_bar.winfo_width() - 2, 2))

    def test_parameters_survive_navigation_without_extra_traces(self):
        self.app.speed.set(0.02)
        self.app.area_vars[0].set(123)
        traces = len(self.app.area_vars[0].trace_info())
        for _ in range(4):
            self.app._about()
            self.app._ai()
            self.app._paint()
            self.app.update()
        self.assertEqual(self.app.speed.get(), 0.02)
        self.assertEqual(self.app.area_vars[0].get(), 123)
        self.assertEqual(len(self.app.area_vars[0].trace_info()), traces)
        self.app.speed.set(0.0001)

    def test_interface_navigation_status_and_ai_preview_states(self):
        self.assertTrue(self.app._status_label.winfo_exists())
        self.assertEqual(self.app._nav[0]["style"], "Selected.Nav.TButton")
        for message, expected in (
            ("正在提取连续轮廓…", "#47677d"),
            ("图片已载入：640 x 480", "#426f52"),
            ("处理失败", "#9b403a"),
            ("就绪", "#59645d"),
        ):
            self.app.status.set(message)
            self.assertEqual(self.app.status.get(), message)
            self.assertEqual(self.app._status_label.cget("fg"), expected)

        self.app._ai()
        self.assertEqual(self.app._nav[1]["style"], "Selected.Nav.TButton")
        self.assertTrue(self.app._ai_preview_canvas.winfo_exists())
        self.app.update()
        self.app._refresh_ai_preview()
        self.assertIsNotNone(self.app._ai_preview_photo)
        self.assertIn("640 × 480", self.app._ai_preview_info.get())

        self.app._about()
        self.assertEqual(self.app._nav[2]["style"], "Selected.Nav.TButton")
        self.app._paint()
        self.assertTrue(self.app.status.get().startswith("图片已载入"))
        self.app.processor = None
        self.app.path.set("未选择图片")
        self.app.progress.set(0)
        self.app._paint()
        self.app.geometry("960x650+30+30")
        self.app.deiconify()
        self.app.update()
        self.app._refresh_preview()
        self.assertEqual(str(self.app.start_button["state"]), "disabled")
        self.assertEqual(self.app.preview_info.get(), "尚未载入")
        x, y = self.app.winfo_rootx(), self.app.winfo_rooty()
        ImageGrab.grab((x, y, x + 960, y + 650)).save(OUTPUT / "gui_empty.png")
        self.app._ai()
        self.app.update()
        self.app._refresh_ai_preview()
        self.assertEqual(self.app._ai_preview_info.get(), "尚未载入图像")
        ImageGrab.grab((x, y, x + 960, y + 650)).save(OUTPUT / "gui_ai_empty.png")
        self.app._about()
        self.app.update()
        ImageGrab.grab((x, y, x + 960, y + 650)).save(OUTPUT / "gui_about.png")

    def test_missing_canvas_never_moves_mouse(self):
        self.process_image()
        self.app._start_drawing()
        self.assertFalse(self.app._drawing)
        self.assertEqual(self.backend.events, [])
        self.assertEqual(len(self.errors), 1)

    def test_stop_during_countdown_and_duplicate_start_guard(self):
        self.process_image()
        left, top, _, _ = desktop_bounds()
        for var, value in zip(self.app.area_vars, (left + 100, top + 100, 320, 240)):
            var.set(value)
        self.app._start_drawing()
        first_worker = self.app.drawing_thread
        self.app._start_drawing()
        self.assertIs(self.app.drawing_thread, first_worker)
        self.app._stop_drawing()
        self.pump_until(lambda: not self.app._drawing)
        self.assertEqual(self.backend.events, [])
        self.assertFalse(first_worker.is_alive())
        self.assertIn("停止", self.app.status.get())

    def test_global_keys_debounce_and_stop(self):
        self.app._drawing = True
        try:
            with mock.patch("ctypes.windll.user32.GetAsyncKeyState",
                            side_effect=lambda key: 0x8000 if key == 0x77 else 0):
                App._poll_keys(self.app)
                App._poll_keys(self.app)
                self.assertTrue(self.app.mouse.paused)
            with mock.patch("ctypes.windll.user32.GetAsyncKeyState", return_value=0):
                App._poll_keys(self.app)
            with mock.patch("ctypes.windll.user32.GetAsyncKeyState",
                            side_effect=lambda key: 0x8000 if key == 0x6B else 0):
                App._poll_keys(self.app)
                self.assertFalse(self.app.mouse.paused)
            with mock.patch("ctypes.windll.user32.GetAsyncKeyState",
                            side_effect=lambda key: 0x8000 if key == 0x1B else 0):
                App._poll_keys(self.app)
                self.assertTrue(self.app.mouse.stopped)
        finally:
            self.app._drawing = False

    def test_arrow_keys_update_live_delay_in_correct_direction(self):
        self.app._drawing = True
        try:
            for key, expected in ((0x26, 0.004), (0x27, 0.003), (0x28, 0.004), (0x25, 0.005)):
                self.app._last_speed_key = 0
                with mock.patch("ctypes.windll.user32.GetAsyncKeyState",
                                side_effect=lambda candidate: 0x8000 if candidate == key else 0):
                    App._poll_keys(self.app)
                self.assertAlmostEqual(self.app._current_delay(), expected)
        finally:
            self.app._drawing = False

    def test_fastest_slider_and_arrow_keys_enter_and_exit_rapid(self):
        self.app.speed.set(0)
        self.assertTrue(self.app._rapid_enabled())
        self.assertIn("极速", self.app.speed_text.get())
        self.app._drawing = True
        try:
            for key, expected in ((0x28, 0.001), (0x26, 0), (0x27, 0)):
                self.app._last_speed_key = 0
                with mock.patch("ctypes.windll.user32.GetAsyncKeyState",
                                side_effect=lambda candidate: 0x8000 if candidate == key else 0):
                    App._poll_keys(self.app)
                self.assertAlmostEqual(self.app._current_delay(), expected)
        finally:
            self.app._drawing = False

    def test_rapid_full_detail_pipeline_under_five_seconds(self):
        self.process_image()
        # Keep the original dense contours; no sharpen call or wait mocking.
        self.assertGreater(sum(map(len, self.app.processor.strokes)), 9000)
        self.app.speed.set(0)
        self.app.countdown.set(0)
        size = (640, 480)
        raster = RasterBackend(size)
        controller = WindowsMouseController(raster)
        original_mouse = self.app.mouse
        self.app.mouse = controller
        config = DrawingConfig((0, 0, *size), self.app.processor.size, countdown=0, lift_delay=0.15)
        strokes = [map_stroke(s, config.image_size, config.target_area) for s in self.app.processor.strokes]
        expected_moves = sum(len(list(interpolate(a, b, config.max_step)))
                             for stroke in strokes for a, b in zip(stroke, stroke[1:]))
        try:
            self.app._drawing = True
            worker = threading.Thread(target=self.app._draw_worker, args=(strokes, config), daemon=True)
            self.app.drawing_thread = worker
            started = time.perf_counter()
            worker.start()
            self.pump_until(lambda: not self.app._drawing, timeout=5)
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 5)
            self.assertTrue(self.app.status.get().startswith("绘画完成"))
            self.assertFalse(raster.held)
            self.assertEqual(sum(event[0] == "move" and event[3] for event in raster.events), expected_moves)
            expected = render_strokes(self.app.processor.strokes, self.app.processor.size, size)
            actual_mask = np.asarray(raster.image)[:, :, 0] < 128
            expected_mask = np.asarray(expected)[:, :, 0] < 128
            self.assertLess(np.count_nonzero(actual_mask ^ expected_mask) / actual_mask.size, 0.015)
            raster.image.save(OUTPUT / "rapid_simulated_canvas.png")
            (OUTPUT / "rapid_timing.json").write_text(json.dumps({
                "backend": "raster simulation, no desktop input",
                "strokes": len(strokes), "source_points": sum(map(len, strokes)),
                "dispatched_move_points": expected_moves, "elapsed_seconds": elapsed,
                "countdown_seconds": 0, "lift_delay_config_seconds": config.lift_delay,
            }, indent=2), encoding="utf-8")
        finally:
            controller.stop()
            worker.join(2)
            self.app.mouse = original_mouse

    def test_ai_model_refresh_and_stale_config_invalidation(self):
        self.app._ai()
        self.app.base_url.set("https://proxy.example/v1")
        self.app.api_key.set("test-key")
        with mock.patch("chenghua_app.list_models",
                        return_value=("OpenAI", ["image-test", "text-test"])):
            self.app._fetch_models()
            self.pump_until(lambda: not self.app._processing)
        self.assertEqual(self.app.model.get(), "image-test")
        self.assertEqual(tuple(self.app._model_combo["values"]), ("image-test", "text-test"))
        self.app.base_url.set("https://other.example/v1")
        self.assertEqual(self.app.model.get(), "")
        self.assertIsNone(self.app._model_signature)
        self.app.api_key.set("")

    def test_models_are_automatically_fetched_after_credentials_change(self):
        self.app._ai()
        with mock.patch("chenghua_app.list_models",
                        return_value=("OpenAI", ["image-auto"])) as listing:
            self.app.base_url.set("https://proxy.example/v1")
            self.app.api_key.set("test-key")
            self.pump_until(lambda: self.app.model.get() == "image-auto")
            listing.assert_called_once()
        self.app.api_key.set("")

    def test_ai_result_is_saved_as_png_and_loaded(self):
        self.app._ai()
        self.app.api_key.set("test-key")
        with mock.patch("chenghua_app.list_models",
                        return_value=("OpenAI", ["image-test"])):
            self.app._fetch_models()
            self.pump_until(lambda: not self.app._processing)
        self.app.prompt.set("a house")
        with mock.patch("chenghua_app.generate_image",
                        return_value=("OpenAI", self.fixture.read_bytes())), \
                tempfile.TemporaryDirectory() as directory:
            with mock.patch("chenghua_app.__file__", str(Path(directory) / "app.py")):
                self.app._generate_ai()
                self.pump_until(lambda: not self.app._processing)
                self.assertEqual(self.app.processor.size, (640, 480))
                self.assertEqual(len(list((Path(directory) / "ai_generated").glob("chenghua_*.png"))), 1)
        self.app.api_key.set("")

    def test_canvas_dialog_does_not_commit_rejected_area(self):
        self.process_image()
        selector = mock.Mock(result=(20, 30, 300, 200))
        with mock.patch("chenghua_app.CanvasSelector", return_value=selector), \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch("chenghua_app.messagebox.askyesno", return_value=False):
            self.app._open_selector()
        self.assertEqual(tuple(v.get() for v in self.app.area_vars), (0, 0, 0, 0))
        with mock.patch("chenghua_app.CanvasSelector", return_value=selector), \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch("chenghua_app.messagebox.askyesno", return_value=True):
            self.app._open_selector()
        self.assertEqual(tuple(v.get() for v in self.app.area_vars), selector.result)

    def test_drawing_cancel_panel_does_not_overlap_canvas(self):
        self.process_image()
        left, top, _, _ = desktop_bounds()
        area = (left + 100, top + 100, 320, 240)
        for var, value in zip(self.app.area_vars, area):
            var.set(value)
        self.app._start_drawing()
        self.app.update()
        panel = self.app._drawing_controls
        self.assertTrue(panel.winfo_ismapped())
        x, y = panel.winfo_rootx(), panel.winfo_rooty()
        self.assertTrue(x + panel.winfo_width() <= area[0] or x >= area[0] + area[2]
                        or y + panel.winfo_height() <= area[1] or y >= area[1] + area[3])
        cancel = next(w for w in panel.winfo_children()[0].winfo_children()
                      if isinstance(w, tk.ttk.Button))
        cancel.invoke()
        self.pump_until(lambda: not self.app._drawing)
        self.assertIsNone(self.app._drawing_controls)
        self.assertEqual(self.backend.events, [])

    def test_selection_reverse_drag_confirm_and_cancel(self):
        self.process_image()
        selector = CanvasSelector(self.app, self.app.processor.strokes, self.app.processor.size)
        self.app.update()
        try:
            selector._press(SimpleNamespace(x=450, y=330))
            selector._drag(SimpleNamespace(x=150, y=110))
            selector._render_preview()
            self.assertIsNotNone(selector.preview_photo)
            self.assertEqual(selector.selection, (150, 110, 300, 220))
            left, top, _, _ = selector.bounds
            selector.confirm()
            self.assertEqual(selector.result, (left + 150, top + 110, 300, 220))
        finally:
            if selector.winfo_exists():
                selector.cancel()
        selector = CanvasSelector(self.app, self.app.processor.strokes, self.app.processor.size)
        selector._press(SimpleNamespace(x=100, y=100))
        selector._drag(SimpleNamespace(x=105, y=105))
        selector.confirm()
        self.assertTrue(selector.winfo_exists())
        selector.cancel()
        self.assertIsNone(selector.result)

    def test_complete_pipeline_renders_to_simulated_canvas(self):
        delay_patcher = mock.patch.object(self.app, "_current_delay", return_value=0)
        delay_patcher.start()
        self.addCleanup(delay_patcher.stop)
        self.process_image()
        self.app.processor.sharpen_strokes(10)
        size = (640, 480)
        raster = RasterBackend(size)
        controller = WindowsMouseController(raster)
        original_mouse = self.app.mouse
        self.app.mouse = controller
        config = DrawingConfig((0, 0, *size), self.app.processor.size,
                               countdown=0, speed=0, extra_delay=0, lift_delay=0.001)
        strokes = [map_stroke(s, config.image_size, config.target_area) for s in self.app.processor.strokes]
        try:
            self.app._drawing = True
            worker = threading.Thread(target=self.app._draw_worker, args=(strokes, config), daemon=True)
            self.app.drawing_thread = worker
            worker.start()
            self.pump_until(lambda: not self.app._drawing, timeout=10)
            self.assertTrue(self.app.status.get().startswith("绘画完成"))
            self.assertEqual(self.app.progress.get(), 100)
            self.assertFalse(raster.held)
            buttons = [e[0] for e in raster.events if e[0] != "move"]
            self.assertEqual(buttons, ["down", "up"] * len(strokes))
            raster.image.save(OUTPUT / "simulated_canvas.png")
            expected = render_strokes(self.app.processor.strokes, self.app.processor.size, size)
            expected.save(OUTPUT / "stroke_preview.png")
            actual_mask = np.asarray(raster.image)[:, :, 0] < 128
            expected_mask = np.asarray(expected)[:, :, 0] < 128
            # Rasterizing interpolated segments may round pixels differently.
            self.assertGreater(np.count_nonzero(actual_mask), 1000)
            self.assertLess(np.count_nonzero(actual_mask ^ expected_mask) / actual_mask.size, 0.015)
        finally:
            controller.stop()
            worker.join(2)
            self.app.mouse = original_mouse

    def test_export_strokes_contains_valid_coordinates(self):
        self.process_image()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "strokes.json"
            with mock.patch("chenghua_app.filedialog.asksaveasfilename", return_value=str(target)):
                self.app._export_strokes()
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved["image_size"], [640, 480])
            self.assertGreater(len(saved["strokes"]), 0)

    def test_layout_small_and_normal_window_screenshots(self):
        self.process_image()
        for width, height in [(960, 650), (1120, 760)]:
            self.app.geometry(f"{width}x{height}+30+30")
            self.app.deiconify()
            self.app.lift()
            self.pump_until(lambda: self.app.winfo_width() == width)
            self.app._refresh_preview()
            self.app.update()
            for button in (self.app.start_button, self.app.pause_button, self.app.stop_button):
                self.assertTrue(button.winfo_ismapped())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                     self.app.winfo_rooty() + self.app.winfo_height())
            self.assertGreater(self.app.preview.winfo_width(), 300)
            viewport = self.app._scroll_views[0]
            viewport.yview_moveto(1)
            self.app.update()
            export_button = next(b for b in self.app._commands if "JSON" in b["text"])
            self.assertLessEqual(export_button.winfo_rooty() + export_button.winfo_height(),
                                 viewport.winfo_rooty() + viewport.winfo_height())
            viewport.yview_moveto(0)
            self.app.update()
            x, y = self.app.winfo_rootx(), self.app.winfo_rooty()
            ImageGrab.grab((x, y, x + width, y + height)).save(OUTPUT / f"gui_{width}.png")
            area_viewport = self.app._scroll_views[1]
            area_viewport.master.master.select(area_viewport.master)
            self.app.update()
            area_viewport.yview_moveto(1)
            self.app.update()
            inner = area_viewport.winfo_children()[0]
            last_row = inner.winfo_children()[-1]
            self.assertLessEqual(last_row.winfo_rooty() + last_row.winfo_height(),
                                 area_viewport.winfo_rooty() + area_viewport.winfo_height())
            ImageGrab.grab((x, y, x + width, y + height)).save(OUTPUT / f"gui_area_{width}.png")
            viewport.master.master.select(viewport.master)
            self.app._ai()
            self.app.update()
            self.assertLessEqual(
                self.app._ai_preview_canvas.winfo_rootx() + self.app._ai_preview_canvas.winfo_width(),
                self.app.winfo_rootx() + self.app.winfo_width(),
            )
            self.assertGreater(self.app._ai_preview_canvas.winfo_width(), 240)
            ImageGrab.grab((x, y, x + width, y + height)).save(OUTPUT / f"gui_ai_{width}.png")
            if width == 1120:
                ImageGrab.grab((x, y, x + width, y + height)).save(OUTPUT / "gui_ai.png")
            self.app._paint()
            self.app.update()


if __name__ == "__main__":
    unittest.main()
