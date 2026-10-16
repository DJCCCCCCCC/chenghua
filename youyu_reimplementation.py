from __future__ import annotations

import ctypes
import io
import json
import logging
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from ai_image import generate_image, list_models
from canvas_selector import CanvasSelector
from drawing_core import (
    DrawingConfig, WindowsMouseController, desktop_bounds,
    enable_dpi_awareness, map_stroke,
)
from image_processing import ImageProcessor, RESAMPLE_LANCZOS, render_strokes
from runtime_paths import application_data_directory


class App(tk.Tk):
    def __init__(self, mouse=None):
        enable_dpi_awareness()
        super().__init__()
        self.title("城画 · 自动绘画")
        self.geometry("1180x780")
        self.minsize(960, 650)
        self.configure(bg="#eef1f4")
        icon = Image.new("RGB", (64, 64), "#176b5b")
        try:
            font = ImageFont.truetype("msyh.ttc", 42)
            ImageDraw.Draw(icon).text((32, 29), "城", fill="white", font=font, anchor="mm")
            self._app_icon = ImageTk.PhotoImage(icon, master=self)
            self.iconphoto(True, self._app_icon)
        except OSError:
            pass
        self.processor = None
        self.preview_photo = None
        self.drawing_thread = None
        self.processing_thread = None
        self.mouse = mouse if mouse is not None else WindowsMouseController()
        self._drawing = self._processing = self._closing = False
        self._queue = queue.Queue()
        self._keys_down = set()
        self._speed_lock = threading.Lock()
        self._live_delay = 0.005
        self._last_speed_key = 0.0
        self._drawing_controls = None
        self._model_combo = None
        self._models_timer = None
        self._model_signature = None
        self._preview_timer = None
        self._nav = []
        self._commands = []
        self._scroll_views = []
        self._ai_preview_canvas = None
        self._ai_preview_photo = None
        self._ai_preview_info = tk.StringVar()
        self.preview_info = tk.StringVar()
        self.canvas_info = tk.StringVar(value="画布未设置")
        self.preview = self.start_button = self.pause_button = self.stop_button = None
        self.status = tk.StringVar(value="就绪")
        self.path = tk.StringVar(value="未选择图片")
        self.progress = tk.DoubleVar(value=0)
        self.blur = tk.IntVar(value=7)
        self.t1 = tk.IntVar(value=50)
        self.t2 = tk.IntVar(value=150)
        self.min_length = tk.IntVar(value=20)
        self.simplify = tk.DoubleVar(value=0)
        self.order = tk.BooleanVar(value=True)
        self.area_vars = [tk.IntVar(value=0) for _ in range(4)]
        self.speed = tk.DoubleVar(value=0.005)
        self.speed_text = tk.StringVar(value="5 ms/点")
        self.step = tk.IntVar(value=5)
        self.countdown = tk.IntVar(value=3)
        self.lift_delay = tk.DoubleVar(value=150)
        self.right_button = tk.BooleanVar(value=False)
        self.keep_aspect = tk.BooleanVar(value=False)
        self.api_key = tk.StringVar(value=os.environ.get(
            "CHENGHUA_API_KEY", os.environ.get("SILICONFLOW_API_KEY", "")))
        default_base = ("https://api.siliconflow.cn/v1"
                        if os.environ.get("SILICONFLOW_API_KEY") and not os.environ.get("CHENGHUA_API_KEY")
                        else "https://api.openai.com/v1")
        self.base_url = tk.StringVar(value=os.environ.get("CHENGHUA_BASE_URL", default_base))
        self.provider = tk.StringVar(value="自动")
        self.model = tk.StringVar()
        self.prompt = tk.StringVar()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<MouseWheel>", self._scroll_wheel, add=True)
        self._build()
        self.status.trace_add("write", self._refresh_status)
        self.speed.trace_add("write", self._speed_changed)
        for variable in (self.base_url, self.api_key, self.provider):
            variable.trace_add("write", self._schedule_models)
        for variable in [*self.area_vars, self.keep_aspect]:
            variable.trace_add("write", self._schedule_preview)
        self.after(30, self._poll)

    def report_callback_exception(self, exc_type, exc_value, traceback):
        logging.error("GUI callback failed", exc_info=(exc_type, exc_value, traceback))
        if not self._closing:
            messagebox.showerror("操作失败", str(exc_value), parent=self)

    def _build(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", "{Microsoft YaHei UI} 10")
        style.configure(".", font=("Microsoft YaHei UI", 10), foreground="#26352f")
        style.configure("TFrame", background="#eef1f4")
        style.configure("White.TFrame", background="white")
        style.configure("TLabel", background="white", foreground="#26352f")
        style.configure("Muted.TLabel", foreground="#697570")
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TCheckbutton", background="white", padding=(0, 4))
        style.map("TCheckbutton", background=[("active", "white")],
                  indicatorbackground=[("selected", "#176b5b")],
                  indicatorforeground=[("selected", "white")])
        style.configure("TButton", padding=(10, 7), background="#f0f3f2", foreground="#33453d",
                        borderwidth=1, bordercolor="#e0e7e3", relief="flat",
                        lightcolor="#f0f3f2", darkcolor="#f0f3f2",
                        focusthickness=1, focuscolor="#176b5b")
        style.map("TButton", background=[("disabled", "#f5f6f5"), ("pressed", "#d8e2dd"), ("active", "#e4ebe7")],
                  foreground=[("disabled", "#929b96")],
                  bordercolor=[("focus", "#176b5b"), ("active", "#b9cbc2")])
        style.configure("Accent.TButton", padding=(12, 10), background="#176b5b", foreground="white",
                        bordercolor="#176b5b", lightcolor="#176b5b", darkcolor="#176b5b", focuscolor="white")
        style.map("Accent.TButton", background=[("disabled", "#dbe8e3"), ("pressed", "#104e42"), ("active", "#125849")],
                  foreground=[("disabled", "#637d70")],
                  bordercolor=[("disabled", "#dbe8e3"), ("focus", "#104e42"), ("!disabled", "#176b5b")])
        style.configure("Danger.TButton", foreground="#9b403a")
        style.map("Danger.TButton", background=[("disabled", "#f5f6f5"), ("active", "#fae8e4")],
                  foreground=[("disabled", "#929b96"), ("!disabled", "#9b403a")])
        style.configure("Nav.TButton", background="#f0f3f2", anchor="w", padding=(16, 10),
                        borderwidth=0, lightcolor="#f0f3f2", darkcolor="#f0f3f2")
        style.map("Nav.TButton", background=[("active", "#e2e9e5")])
        style.configure("Selected.Nav.TButton", background="#dce9e2", foreground="#135a4d",
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Selected.Nav.TButton", background=[("active", "#d2e3d9")])
        style.configure("TEntry", padding=(8, 6), bordercolor="#d7dfe4",
                        lightcolor="white", darkcolor="white", fieldbackground="white")
        style.configure("TSpinbox", padding=(4, 3), bordercolor="#d7dfe4",
                        lightcolor="white", darkcolor="white", arrowsize=12)
        style.configure("TCombobox", padding=(8, 6), bordercolor="#d7dfe4",
                        lightcolor="white", darkcolor="white", arrowsize=12)
        style.map("TCombobox", fieldbackground=[("readonly", "#f6f8f9")],
                  background=[("readonly", "#eef2f4")])
        for control in ("TEntry", "TSpinbox", "TCombobox"):
            style.map(control, bordercolor=[("focus", "#176b5b")])
        self._scale_images = []
        for fill in ("#176b5b", "#125849"):
            image = Image.new("RGBA", (24, 24))
            ImageDraw.Draw(image).ellipse((3, 3, 20, 20), fill=fill, outline="white", width=2)
            self._scale_images.append(ImageTk.PhotoImage(image, master=self))
        style.element_create("Chenghua.Scale.slider", "image", self._scale_images[0],
                             ("active", self._scale_images[1]))
        track = Image.new("RGB", (40, 24), "white")
        ImageDraw.Draw(track).rounded_rectangle((0, 10, 39, 13), radius=2, fill="#dce5df")
        self._scale_track = ImageTk.PhotoImage(track, master=self)
        style.element_create("Chenghua.Scale.trough", "image", self._scale_track,
                             border=(8, 0, 8, 0), sticky="ew")
        style.layout("Horizontal.TScale", [("Chenghua.Scale.trough", {
            "sticky": "we", "children": [("Chenghua.Scale.slider", {"side": "left", "sticky": ""})]})])
        style.configure("Horizontal.TScale", background="white", troughcolor="#e3e9eb",
                        borderwidth=0, troughborderwidth=0, lightcolor="white", darkcolor="white")
        self._progress_images = [ImageTk.PhotoImage(Image.new("RGB", (8, 4), color), master=self)
                                 for color in ("#e5eeea", "#378e79")]
        style.element_create("Chenghua.Progress.trough", "image", self._progress_images[0],
                             border=0, sticky="nswe")
        style.element_create("Chenghua.Progress.pbar", "image", self._progress_images[1],
                             border=0, sticky="nswe")
        style.layout("Horizontal.TProgressbar", [("Chenghua.Progress.trough", {
            "sticky": "nswe", "children": [("Chenghua.Progress.pbar", {"side": "left", "sticky": "ns"})]})])
        style.configure("Horizontal.TProgressbar", background="#378e79", troughcolor="#e5eeea",
                        borderwidth=0, thickness=4, lightcolor="#378e79", darkcolor="#378e79")
        style.configure("TNotebook", background="white", borderwidth=0,
                        bordercolor="white", lightcolor="white", darkcolor="white", tabmargins=(0, 0, 0, 8))
        style.configure("TNotebook.Tab", padding=(15, 8), background="#f0f3f2", borderwidth=0,
                        bordercolor="white", lightcolor="white", darkcolor="white", focuscolor="#176b5b")
        style.map("TNotebook.Tab", background=[("selected", "#dce9e2"), ("active", "#e7ede9")],
                  foreground=[("selected", "#145e4f")], padding=[("selected", (15, 8))])
        style.configure("Vertical.TScrollbar", arrowsize=12, background="#d2dad6", borderwidth=0,
                        troughcolor="white", bordercolor="white", lightcolor="white", darkcolor="white")
        style.map("Vertical.TScrollbar", background=[("active", "#aebfb5")])
        self._separator_image = ImageTk.PhotoImage(Image.new("RGB", (2, 1), "#e2e8e4"), master=self)
        style.element_create("Chenghua.Separator", "image", self._separator_image, sticky="ew")
        style.layout("TSeparator", [("Chenghua.Separator", {"sticky": "ew"})])
        sidebar = tk.Frame(self, bg="#f0f3f2", width=152)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="城画", font=("Microsoft YaHei UI", 22, "bold"),
                 bg="#f0f3f2", fg="#174f46").pack(anchor="w", padx=24, pady=(26, 0))
        tk.Label(sidebar, text="自动绘画工作台", font=("Microsoft YaHei UI", 9),
                 bg="#f0f3f2", fg="#697570").pack(anchor="w", padx=24, pady=(3, 26))
        for label, command in [("绘画", self._paint), ("AI 生图", self._ai), ("关于", self._about)]:
            button = ttk.Button(sidebar, text=label, command=command, style="Nav.TButton")
            button.pack(fill="x", padx=12, pady=3)
            self._nav.append(button)
        tk.Label(sidebar, text="城画  /  0.4.0", font=("Microsoft YaHei UI", 9),
                 bg="#f0f3f2", fg="#697570").pack(side="bottom", anchor="w", padx=24, pady=20)
        shell = ttk.Frame(self, style="White.TFrame")
        shell.pack(fill="both", expand=True)
        footer = tk.Frame(shell, bg="#f7f9f8", height=38, padx=20)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        self._status_label = tk.Label(footer, textvariable=self.status, anchor="w",
                                      bg="#f7f9f8", fg="#59645d", font=("Microsoft YaHei UI", 9))
        self._status_label.pack(side="left", fill="both", expand=True)
        self._status_label.bind("<Configure>", lambda event: self._status_label.configure(
            wraplength=max(120, event.width - 8)))
        self.content = ttk.Frame(shell, style="White.TFrame", padding=(20, 22, 20, 18))
        self.content.pack(fill="both", expand=True)
        self._paint()

    def _refresh_status(self, *_args):
        message = self.status.get()
        color = ("#9b403a" if any(word in message for word in ("失败", "错误")) else
                 "#47677d" if any(word in message for word in ("正在", "准备", "后开始")) else
                 "#426f52" if any(word in message for word in ("已", "完成")) else "#59645d")
        self._status_label.configure(fg=color)

    def _page_header(self, title, detail=None):
        row = ttk.Frame(self.content, style="White.TFrame")
        row.pack(fill="x", pady=(0, 20))
        ttk.Label(row, text=title, font=("Microsoft YaHei UI", 18, "bold")).pack(side="left")
        if detail is not None:
            ttk.Label(row, textvariable=detail, style="Muted.TLabel").pack(side="right")

    def _select_nav(self, index):
        for position, button in enumerate(self._nav):
            button.configure(style="Selected.Nav.TButton" if position == index else "Nav.TButton")

    def _clear_content(self):
        if self._preview_timer:
            self.after_cancel(self._preview_timer)
            self._preview_timer = None
        for child in self.content.winfo_children():
            child.destroy()
        self._commands = []
        self._scroll_views = []
        self._model_combo = None
        self._ai_preview_canvas = None
        self._ai_preview_photo = None
        if self._models_timer:
            self.after_cancel(self._models_timer)
            self._models_timer = None
        self.preview = self.start_button = self.pause_button = self.stop_button = None

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self._commands.append(button)
        return button

    @staticmethod
    def _number(parent, label, variable, low, high, increment=1):
        row = ttk.Frame(parent, style="White.TFrame")
        row.pack(fill="x", pady=5)
        ttk.Label(row, text=label).pack(side="left")
        ttk.Spinbox(row, textvariable=variable, from_=low, to=high,
                    increment=increment, width=10).pack(side="right")

    def _speed_changed(self, *_args):
        try:
            delay = min(0.1, max(0, float(self.speed.get())))
            if delay < 0.0005:
                delay = 0
        except (tk.TclError, ValueError):
            return
        with self._speed_lock:
            self._live_delay = delay
        self.speed_text.set("极速 · 零等待" if delay == 0 else "{:.0f} ms/点".format(delay * 1000))

    def _current_delay(self):
        with self._speed_lock:
            return self._live_delay

    def _rapid_enabled(self):
        return self._current_delay() == 0

    def _tab_body(self, tabs, title):
        page = ttk.Frame(tabs, style="White.TFrame")
        tabs.add(page, text=title)
        scrollbar = ttk.Scrollbar(page, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        viewport = tk.Canvas(page, bg="white", highlightthickness=0, width=1, height=1,
                             yscrollcommand=scrollbar.set)
        viewport.pack(fill="both", expand=True)
        scrollbar.configure(command=viewport.yview)
        inner = ttk.Frame(viewport, style="White.TFrame", padding=8)
        item = viewport.create_window(0, 0, window=inner, anchor="nw")
        viewport.bind("<Configure>", lambda event: viewport.itemconfigure(item, width=event.width))
        inner.bind("<Configure>", lambda _event: viewport.configure(scrollregion=viewport.bbox("all")))
        self._scroll_views.append(viewport)
        return inner

    def _scroll_wheel(self, event):
        for viewport in self._scroll_views:
            if not viewport.winfo_ismapped():
                continue
            x, y = event.x_root - viewport.winfo_rootx(), event.y_root - viewport.winfo_rooty()
            if 0 <= x < viewport.winfo_width() and 0 <= y < viewport.winfo_height():
                viewport.yview_scroll(-int(event.delta / 120), "units")
                return "break"

    def _paint(self):
        if self._drawing or self._processing:
            return
        self._clear_content()
        self._select_nav(0)
        self._page_header("绘画工作台", self.canvas_info)
        body = ttk.Frame(self.content, style="White.TFrame")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="White.TFrame", width=304)
        left.pack(side="left", fill="y", padx=(0, 20))
        left.pack_propagate(False)
        actions = ttk.Frame(left, style="White.TFrame")
        actions.pack(side="bottom", fill="x", pady=(16, 0))
        ttk.Separator(actions).pack(fill="x", pady=(0, 12))
        speed_row = ttk.Frame(actions, style="White.TFrame")
        speed_row.pack(fill="x", pady=(0, 3))
        ttk.Label(speed_row, text="绘画速度", style="Section.TLabel").pack(side="left")
        ttk.Label(speed_row, textvariable=self.speed_text, foreground="#176b5b").pack(side="right")
        ttk.Scale(actions, variable=self.speed, from_=0.1, to=0,
                  command=lambda _value: self._speed_changed()).pack(fill="x", pady=(0, 2))
        speed_ends = ttk.Frame(actions, style="White.TFrame")
        speed_ends.pack(fill="x", pady=(0, 9))
        ttk.Label(speed_ends, text="稳定", style="Muted.TLabel").pack(side="left")
        ttk.Label(speed_ends, text="极速", foreground="#176b5b").pack(side="right")
        self.start_button = ttk.Button(actions, text="开始绘画", style="Accent.TButton", command=self._start_drawing)
        self.start_button.pack(fill="x")
        row = ttk.Frame(actions, style="White.TFrame")
        row.pack(fill="x", pady=6)
        self.pause_button = ttk.Button(row, text="暂停", command=self._toggle_pause)
        self.pause_button.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.stop_button = ttk.Button(row, text="取消绘画", style="Danger.TButton", command=self._stop_drawing)
        self.stop_button.pack(side="left", fill="x", expand=True, padx=(3, 0))
        self.progress_bar = ttk.Progressbar(actions, variable=self.progress, maximum=100)
        self.progress_bar.pack(fill="x", pady=(6, 0))
        tabs = ttk.Notebook(left)
        tabs.pack(fill="both", expand=True)
        image_tab = self._tab_body(tabs, "图像处理")
        area_tab = self._tab_body(tabs, "画布设置")
        image_actions = ttk.Frame(image_tab, style="White.TFrame")
        image_actions.pack(fill="x")
        self._button(image_actions, "选择图片", self._select_image).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        self._button(image_actions, "处理图片", self._process_image).pack(
            side="left", fill="x", expand=True)
        ttk.Label(image_tab, textvariable=self.path, wraplength=258, style="Muted.TLabel").pack(anchor="w", pady=(8, 12))
        self._number(image_tab, "模糊核", self.blur, 1, 15, 2)
        self._number(image_tab, "低阈值", self.t1, 0, 255)
        self._number(image_tab, "高阈值", self.t2, 0, 255)
        self._number(image_tab, "最短轮廓", self.min_length, 0, 1000)
        self._number(image_tab, "简化精度 (px)", self.simplify, 0, 10, 0.1)
        ttk.Checkbutton(image_tab, text="从上到下排序", variable=self.order).pack(anchor="w", pady=5)
        self._button(image_tab, "简化当前笔画", self._sharpen).pack(fill="x", pady=4)
        self._button(image_tab, "导出笔画 JSON", self._export_strokes).pack(fill="x", pady=4)
        self._button(area_tab, "框选画布", self._select_area).pack(fill="x", pady=(0, 5))
        for label, var, low in zip(("X", "Y", "宽度", "高度"), self.area_vars, (-99999, -99999, 0, 0)):
            self._number(area_tab, label, var, low, 99999)
        ttk.Checkbutton(area_tab, text="保持图像比例", variable=self.keep_aspect).pack(anchor="w", pady=3)
        ttk.Checkbutton(area_tab, text="使用鼠标右键", variable=self.right_button).pack(anchor="w", pady=3)
        self._number(area_tab, "插值步长 (px)", self.step, 1, 100, 1)
        self._number(area_tab, "落笔前等待 (ms)", self.lift_delay, 0, 3000, 10)
        self._number(area_tab, "倒计时 (秒)", self.countdown, 0, 30, 1)
        right = ttk.Frame(body, style="White.TFrame")
        right.pack(side="left", fill="both", expand=True)
        heading = ttk.Frame(right, style="White.TFrame")
        heading.pack(fill="x", pady=(6, 12))
        ttk.Label(heading, text="笔画预览", style="Section.TLabel").pack(side="left")
        ttk.Label(heading, textvariable=self.preview_info, style="Muted.TLabel").pack(side="right")
        self.preview = tk.Canvas(right, bg="#f3f5f4", highlightthickness=1,
                                 highlightbackground="#e1e7e3", width=1, height=1)
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Configure>", self._schedule_preview)
        if self.processor is not None and self.processor.processed:
            self._processed_status()
        elif self.processor is not None:
            self.status.set("图片已载入：{} x {}".format(*self.processor.size))
        else:
            self.status.set("就绪")
        self._set_controls()
        self._schedule_preview()

    def _set_controls(self):
        busy = self._drawing or self._processing
        for widget in [*self._nav, *self._commands]:
            widget.configure(state="disabled" if busy else "normal")
        if self.start_button:
            ready = self.processor is not None and bool(self.processor.strokes)
            self.start_button.configure(state="normal" if ready and not busy else "disabled")
            self.pause_button.configure(state="normal" if self._drawing else "disabled",
                                        text="继续" if self.mouse.paused else "暂停")
            self.stop_button.configure(state="normal" if self._drawing else "disabled")

    def _schedule_preview(self, *_args):
        if self._closing or not self.preview:
            return
        if self._preview_timer:
            self.after_cancel(self._preview_timer)
        self._preview_timer = self.after(80, self._refresh_preview)

    def _refresh_preview(self):
        self._preview_timer = None
        if not self.preview:
            return
        canvas = self.preview
        canvas.delete("all")
        width, height = max(1, canvas.winfo_width() - 24), max(1, canvas.winfo_height() - 24)
        try:
            target_w, target_h = self.area_vars[2].get(), self.area_vars[3].get()
        except tk.TclError:
            target_w = target_h = 0
        self.canvas_info.set("画布  {} × {}".format(target_w, target_h)
                             if min(target_w, target_h) > 0 else "画布未设置")
        if self.processor is None:
            self.preview_info.set("尚未载入")
            self._empty_preview(canvas, "未选择图片")
            return
        self.preview_info.set("{} 笔".format(len(self.processor.strokes)) if self.processor.processed
                              else "{} × {}".format(*self.processor.size))
        if not self.processor.processed:
            image = self.processor.original.copy()
            image.thumbnail((width, height), RESAMPLE_LANCZOS)
        else:
            try:
                target_w, target_h = self.area_vars[2].get(), self.area_vars[3].get()
            except tk.TclError:
                target_w = target_h = 0
            if min(target_w, target_h) <= 0:
                target_w, target_h = self.processor.size
            scale = min(width / target_w, height / target_h)
            size = max(1, round(target_w * scale)), max(1, round(target_h * scale))
            image = render_strokes(self.processor.strokes, self.processor.size, size, self.keep_aspect.get())
        self.preview_photo = ImageTk.PhotoImage(image, master=self)
        canvas.create_image(canvas.winfo_width() // 2, canvas.winfo_height() // 2, image=self.preview_photo)

    @staticmethod
    def _empty_preview(canvas, label):
        width, height = canvas.winfo_width(), canvas.winfo_height()
        canvas.create_text(width // 2, height // 2, text=label, fill="#697570",
                           font=("Microsoft YaHei UI", 11), width=max(1, width - 32))

    def _select_image(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[
            ("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.gif"), ("所有文件", "*.*")])
        if path:
            self._load_image(path)

    def _load_image(self, path):
        try:
            self.processor = ImageProcessor(path)
            self.path.set(Path(path).name)
            self.status.set("图片已载入：{} x {}".format(*self.processor.size))
            self.progress.set(0)
            self._schedule_preview()
            self._set_controls()
        except Exception as exc:
            messagebox.showerror("载入失败", str(exc), parent=self)

    def _process_image(self):
        if self._drawing or self._processing:
            return
        if self.processor is None:
            messagebox.showinfo("处理图片", "请先选择图片。", parent=self)
            return
        try:
            parameters = (self.blur.get(), self.t1.get(), self.t2.get(),
                          self.min_length.get(), self.simplify.get(), self.order.get())
            if not (1 <= parameters[0] <= 51 and 0 <= parameters[1] <= parameters[2] <= 255
                    and parameters[3] >= 0 and 0 <= parameters[4] <= 100):
                raise ValueError("请检查模糊核、阈值和轮廓参数。")
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("参数错误", str(exc), parent=self)
            return
        self._processing = True
        self.status.set("正在提取连续轮廓…")
        self.progress.set(0)
        self._set_controls()
        self.processing_thread = threading.Thread(target=self._process_worker,
                                                  args=(self.processor, parameters), daemon=True)
        self.processing_thread.start()

    def _process_worker(self, processor, parameters):
        try:
            processor.preprocess(*parameters[:3])
            processor.extract_strokes(*parameters[3:])
            self._queue.put(("processed", None))
        except Exception as exc:
            self._queue.put(("process_error", str(exc)))

    def _sharpen(self):
        if self.processor is not None and self.processor.strokes:
            self.processor.sharpen_strokes()
            self._processed_status()
            self._schedule_preview()

    def _export_strokes(self):
        if self.processor is None or not self.processor.strokes:
            messagebox.showinfo("导出笔画", "请先处理图片。", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            data = {"image_size": self.processor.size, "strokes": self.processor.strokes}
            Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.status.set("笔画已导出")

    def _select_area(self):
        if self.processor is None or not self.processor.strokes:
            messagebox.showinfo("框选画布", "请先处理图片并生成笔画。", parent=self)
            return
        self.iconify()
        self.after(200, self._open_selector)

    def _open_selector(self):
        if self._closing:
            return
        try:
            selector = CanvasSelector(self, self.processor.strokes, self.processor.size, self.keep_aspect.get())
            self.wait_window(selector)
            if selector.result:
                self.deiconify()
                x, y, width, height = selector.result
                accepted = messagebox.askyesno(
                    "确认画布区域",
                    "使用选定区域作为绘画画布？\n\n位置：{}, {}\n尺寸：{} × {}".format(x, y, width, height),
                    parent=self,
                )
                if accepted:
                    for variable, value in zip(self.area_vars, selector.result):
                        variable.set(value)
                    self.status.set("已确认画布：{} × {}".format(width, height))
        except Exception as exc:
            messagebox.showerror("框选失败", str(exc), parent=self)
        finally:
            if not self._closing:
                self.deiconify()
                self.lift()

    def _start_drawing(self):
        if self._drawing or self._processing or (self.drawing_thread and self.drawing_thread.is_alive()):
            return
        if self.processor is None or not self.processor.strokes:
            return
        try:
            config = DrawingConfig(
                area=tuple(v.get() for v in self.area_vars), image_size=self.processor.size,
                speed=self.speed.get(), max_step=self.step.get(), countdown=self.countdown.get(),
                extra_delay=0, lift_delay=self.lift_delay.get() / 1000,
                right_button=self.right_button.get(), keep_aspect=self.keep_aspect.get())
            config.validate(desktop_bounds())
            strokes = [map_stroke(stroke, config.image_size, config.target_area) for stroke in self.processor.strokes]
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("无法开始", "请先框选有效画布，并检查绘画参数。\n" + str(exc), parent=self)
            return
        self.mouse.reset_stop()
        self._keys_down.clear()
        self._last_speed_key = 0.0
        self._drawing = True
        self.progress.set(0)
        self.status.set("准备绘画")
        self._set_controls()
        self._show_drawing_controls(config.area)
        self.iconify()
        self.drawing_thread = threading.Thread(target=self._draw_worker, args=(strokes, config), daemon=True)
        self.drawing_thread.start()

    def _draw_worker(self, strokes, config):
        outcome = "绘画已停止"
        try:
            for remaining in range(config.countdown, 0, -1):
                self._queue.put(("status", "{} 秒后开始绘画".format(remaining)))
                if not self.mouse.wait(1):
                    return
            started = time.perf_counter()
            for index, stroke in enumerate(strokes):
                if not self.mouse.draw_stroke(stroke, self._current_delay, config.max_step,
                                              config.right_button, config.lift_delay,
                                              rapid=self._rapid_enabled):
                    return
                self._queue.put(("progress", (index + 1, len(strokes))))
            outcome = "绘画完成 · {:.2f} 秒".format(time.perf_counter() - started)
        except Exception as exc:
            logging.exception("Drawing failed")
            outcome = "绘画失败：" + str(exc)
        finally:
            try:
                self.mouse.release()
            finally:
                self._queue.put(("draw_done", outcome))

    def _toggle_pause(self):
        if not self._drawing or self.mouse.stopped:
            return
        if self.mouse.paused:
            self.mouse.resume()
            self.status.set("继续绘画")
        else:
            self.mouse.pause()
            self.status.set("绘画已暂停")
        self._set_controls()

    def _stop_drawing(self):
        if self._drawing:
            self.mouse.stop()
            self.status.set("正在停止绘画")

    def _show_drawing_controls(self, area):
        self._hide_drawing_controls()
        panel = tk.Toplevel(self)
        self._drawing_controls = panel
        panel.title("城画正在绘画")
        panel.overrideredirect(True)
        panel.resizable(False, False)
        panel.geometry("292x210")
        panel.pack_propagate(False)
        panel.attributes("-topmost", True)
        panel.configure(bg="#f7f9f8")
        panel.protocol("WM_DELETE_WINDOW", self._stop_drawing)
        frame = tk.Frame(panel, bg="#f7f9f8", padx=14, pady=11)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="城画正在绘画", font=("Microsoft YaHei UI", 11, "bold"),
                 bg="#f7f9f8", fg="#174f46").pack(anchor="w")
        tk.Label(frame, text="方向键调速  ·  Esc 取消", bg="#f7f9f8",
                 fg="#58686a").pack(anchor="w", pady=(3, 7))
        tk.Label(frame, textvariable=self.status, bg="#f7f9f8",
                 fg="#26313d", wraplength=260).pack(anchor="w", pady=(0, 8))
        tk.Label(frame, textvariable=self.speed_text, bg="#f7f9f8", fg="#176b5b").pack(anchor="w", pady=(0, 8))
        ttk.Button(frame, text="取消绘画", style="Danger.TButton", command=self._stop_drawing).pack(fill="x")
        panel.update_idletasks()
        left, top, sw, sh = desktop_bounds()
        pw, ph = panel.winfo_width(), panel.winfo_height()
        x, y, width, height = area
        positions = ((left + sw - pw - 12, top + 12), (left + 12, top + 12),
                     (left + 12, top + sh - ph - 12), (left + sw - pw - 12, top + sh - ph - 12))
        for px, py in positions:
            if px + pw <= x or px >= x + width or py + ph <= y or py >= y + height:
                panel.geometry("{}x{}+0+0".format(pw, ph))
                panel.update_idletasks()
                user32 = ctypes.windll.user32
                user32.GetParent.argtypes = [ctypes.c_void_p]
                user32.GetParent.restype = ctypes.c_void_p
                user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                               ctypes.c_int, ctypes.c_uint]
                hwnd = user32.GetParent(panel.winfo_id()) or panel.winfo_id()
                user32.SetWindowPos(hwnd, -1, px, py, pw, ph, 0x0010 | 0x0040)
                break
        else:
            panel.withdraw()
            messagebox.showinfo("城画 · 绘画控制",
                                "选区外没有空间放置控制条。\n绘画中按 Esc 取消，F8 暂停，方向键调速。",
                                parent=self)

    def _hide_drawing_controls(self):
        if self._drawing_controls is not None:
            try:
                self._drawing_controls.destroy()
            except tk.TclError:
                pass
            self._drawing_controls = None

    def _poll_keys(self):
        if not self._drawing or self.mouse.stopped or os.name != "nt":
            return
        down = {key for key in (0x1B, 0x6D, 0x77, 0x6B, 0x25, 0x26, 0x27, 0x28)
                if ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000}
        pressed = down - self._keys_down
        self._keys_down = down
        if pressed & {0x1B, 0x6D}:
            self._stop_drawing()
            return
        elif 0x77 in pressed:
            self._toggle_pause()
        elif 0x6B in pressed and self.mouse.paused:
            self._toggle_pause()
        speed_keys = down & {0x25, 0x26, 0x27, 0x28}
        now = time.monotonic()
        if speed_keys and now - self._last_speed_key >= 0.12:
            delta = -0.001 if speed_keys & {0x26, 0x27} else 0.001
            self._last_speed_key = now
            self.speed.set(min(0.1, max(0, self._current_delay() + delta)))
            self.status.set("绘画速度：" + self.speed_text.get())

    def _processed_status(self):
        strokes = self.processor.strokes
        self.status.set("已生成 {} 笔，{} 个路径点".format(len(strokes), sum(map(len, strokes)))
                        if strokes else "未检测到有效轮廓，请降低最短轮廓或调整阈值。")

    def _poll(self):
        if self._closing:
            return
        self._poll_keys()
        for _ in range(100):
            try:
                event, value = self._queue.get_nowait()
            except queue.Empty:
                break
            if event == "status" and not self.mouse.stopped and not self.mouse.paused:
                self.status.set(value)
            elif event == "progress" and not self.mouse.stopped:
                completed, total = value
                self.progress.set(completed / total * 100)
                if not self.mouse.paused:
                    self.status.set("正在绘画：{} / {} 笔".format(completed, total))
            elif event == "processed":
                self._processing = False
                self._processed_status()
                self.progress.set(100)
                self._schedule_preview()
                self._set_controls()
            elif event in ("process_error", "ai_error"):
                self._processing = False
                self.status.set("处理失败")
                self._set_controls()
                messagebox.showerror("处理失败", value, parent=self)
            elif event in ("models_done", "models_error"):
                signature, result = value
                self._processing = False
                if signature == self._connection():
                    if event == "models_done":
                        provider, models = result
                        self._model_signature = signature
                        self._model_combo.configure(values=models)
                        if self.model.get() not in models:
                            self.model.set(models[0])
                        self.status.set("{} · 已获取 {} 个模型".format(provider, len(models)))
                    else:
                        self.status.set("模型获取失败：" + result)
                else:
                    self._schedule_models()
                self._set_controls()
            elif event == "draw_done":
                self._finish_drawing(value)
            elif event == "ai_done":
                self._processing = False
                self._paint()
                self._load_image(value)
        self.after(30, self._poll)

    def _finish_drawing(self, outcome):
        if self._closing:
            return
        if self.drawing_thread and self.drawing_thread.is_alive():
            self.after(30, lambda: self._finish_drawing(outcome))
            return
        self._drawing = False
        self.status.set(outcome)
        self._hide_drawing_controls()
        self._set_controls()
        self.deiconify()
        self.lift()

    def _ai(self):
        if self._drawing or self._processing:
            return
        self._clear_content()
        self._select_nav(1)
        self.status.set("未连接" if not self.api_key.get().strip() else "就绪")
        self._page_header("AI 生图")
        body = ttk.Frame(self.content, style="White.TFrame")
        body.pack(fill="both", expand=True)
        form = ttk.Frame(body, style="White.TFrame", width=336)
        form.pack(side="left", fill="y", padx=(0, 24))
        form.pack_propagate(False)
        ttk.Label(form, text="服务连接", style="Section.TLabel").pack(anchor="w", pady=(4, 14))
        format_row = ttk.Frame(form, style="White.TFrame")
        format_row.pack(fill="x", pady=(0, 12))
        ttk.Label(format_row, text="接口格式").pack(side="left")
        provider_combo = ttk.Combobox(format_row, textvariable=self.provider, state="readonly",
                                     values=("自动", "OpenAI", "Gemini"), width=16)
        provider_combo.pack(side="right")
        provider_combo.bind("<<ComboboxSelected>>", self._provider_selected)
        ttk.Label(form, text="Base URL").pack(anchor="w")
        ttk.Entry(form, textvariable=self.base_url).pack(fill="x", pady=(5, 12))
        ttk.Label(form, text="API Key").pack(anchor="w")
        ttk.Entry(form, textvariable=self.api_key, show="*").pack(fill="x", pady=(5, 12))
        ttk.Label(form, text="模型").pack(anchor="w")
        row = ttk.Frame(form, style="White.TFrame")
        row.pack(fill="x", pady=(5, 0))
        self._model_combo = ttk.Combobox(row, textvariable=self.model, state="readonly", width=12)
        self._model_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._button(row, "刷新模型", self._fetch_models).pack(side="right")
        ttk.Separator(form).pack(fill="x", pady=(18, 14))
        generate_button = self._button(form, "生成图片", self._generate_ai)
        generate_button.configure(style="Accent.TButton")
        generate_button.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Label(form, text="提示词", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        prompt = tk.Text(form, height=5, font=("Microsoft YaHei UI", 10), wrap="word",
                         relief="flat", borderwidth=0, highlightthickness=1,
                         highlightbackground="#d7dfe4", highlightcolor="#176b5b", padx=10, pady=8,
                         foreground="#26352f", background="#fbfcfb", insertbackground="#176b5b")
        prompt.insert("1.0", self.prompt.get())
        prompt.pack(fill="both", expand=True)

        def sync_prompt(_event):
            if prompt.edit_modified():
                self.prompt.set(prompt.get("1.0", "end-1c"))
                prompt.edit_modified(False)
        prompt.bind("<<Modified>>", sync_prompt)
        preview = ttk.Frame(body, style="White.TFrame")
        preview.pack(side="left", fill="both", expand=True)
        ttk.Label(preview, text="当前图像", style="Section.TLabel").pack(anchor="w", pady=(4, 14))
        ttk.Label(preview, textvariable=self._ai_preview_info, style="Muted.TLabel").pack(
            side="bottom", anchor="w", pady=(10, 0))
        self._ai_preview_canvas = tk.Canvas(preview, bg="#f3f5f4", highlightthickness=1,
                                            highlightbackground="#e1e7e3", width=1, height=1)
        self._ai_preview_canvas.pack(fill="both", expand=True)
        self._ai_preview_canvas.bind("<Configure>", self._refresh_ai_preview)
        self._set_controls()
        self._schedule_models()

    def _refresh_ai_preview(self, _event=None):
        canvas = self._ai_preview_canvas
        if not canvas:
            return
        canvas.delete("all")
        if self.processor is None:
            self._ai_preview_info.set("尚未载入图像")
            self._empty_preview(canvas, "暂无图像")
            return
        image = self.processor.original.copy()
        image.thumbnail((max(1, canvas.winfo_width() - 32),
                         max(1, canvas.winfo_height() - 32)), RESAMPLE_LANCZOS)
        self._ai_preview_photo = ImageTk.PhotoImage(image, master=self)
        canvas.create_image(canvas.winfo_width() // 2, canvas.winfo_height() // 2,
                            image=self._ai_preview_photo)
        self._ai_preview_info.set("{} × {}".format(*self.processor.size))

    def _provider_selected(self, _event=None):
        if self.provider.get() == "Gemini" and self.base_url.get() == "https://api.openai.com/v1":
            self.base_url.set("https://generativelanguage.googleapis.com/v1beta")
        elif self.provider.get() == "OpenAI" and "generativelanguage.googleapis.com" in self.base_url.get():
            self.base_url.set("https://api.openai.com/v1")

    def _connection(self):
        return self.base_url.get().strip(), self.api_key.get().strip(), self.provider.get()

    def _schedule_models(self, *_args):
        self.model.set("")
        self._model_signature = None
        if self._models_timer:
            self.after_cancel(self._models_timer)
            self._models_timer = None
        if self._model_combo and self._model_combo.winfo_exists():
            self._model_combo.configure(values=())
            if self.base_url.get().strip() and self.api_key.get().strip():
                self._models_timer = self.after(900, self._fetch_models)

    def _fetch_models(self):
        if self._models_timer:
            self.after_cancel(self._models_timer)
        self._models_timer = None
        if self._processing or self._drawing or not self._model_combo:
            return
        signature = self._connection()
        if not signature[1]:
            self.status.set("请填写 API Key")
            return
        self._processing = True
        self.status.set("正在获取可用模型…")
        self._set_controls()
        self.processing_thread = threading.Thread(target=self._models_worker, args=(signature,), daemon=True)
        self.processing_thread.start()

    def _models_worker(self, signature):
        try:
            base, key, provider = signature
            result = list_models(base, key, provider)
            self._queue.put(("models_done", (signature, result)))
        except Exception as exc:
            self._queue.put(("models_error", (signature, str(exc))))

    def _generate_ai(self):
        if self._drawing or self._processing:
            return
        base, key, provider = self._connection()
        prompt, model = self.prompt.get().strip(), self.model.get().strip()
        if not key or not prompt or not model or self._model_signature != self._connection():
            messagebox.showinfo("城画 · AI 生图", "请获取模型、选择模型并填写提示词。", parent=self)
            return
        self._processing = True
        self.status.set("正在生成图片")
        self._set_controls()
        self.processing_thread = threading.Thread(target=self._ai_worker,
                                                  args=(base, key, provider, model, prompt), daemon=True)
        self.processing_thread.start()

    def _ai_worker(self, base, key, provider, model, prompt):
        try:
            _, image_data = generate_image(base, key, model, prompt, provider)
            directory = application_data_directory(__file__) / "ai_generated"
            directory.mkdir(exist_ok=True)
            path = directory / "chenghua_{}.png".format(time.time_ns())
            with Image.open(io.BytesIO(image_data)) as image:
                image.save(path, format="PNG")
            self._queue.put(("ai_done", str(path)))
        except Exception as exc:
            self._queue.put(("ai_error", str(exc)))

    def _about(self):
        if self._drawing or self._processing:
            return
        self._clear_content()
        self._select_nav(2)
        self._page_header("关于城画")
        ttk.Label(self.content, text="城画", font=("Microsoft YaHei UI", 24, "bold"),
                  foreground="#174f46").pack(anchor="w", pady=(20, 6))
        ttk.Label(self.content, text="自动绘画工具  /  0.4.0", style="Muted.TLabel").pack(anchor="w")
        ttk.Separator(self.content).pack(fill="x", pady=28)
        for title, detail in (
            ("本地图像处理", "图像处理与笔画生成在本地完成。"),
            ("自定义生图服务", "AI 生图连接你配置的服务，密钥仅保留在当前会话。"),
        ):
            ttk.Label(self.content, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 6))
            ttk.Label(self.content, text=detail, style="Muted.TLabel", wraplength=580).pack(anchor="w", pady=(0, 24))
        self.status.set("城画 · 自动绘画工具")

    def _close(self):
        self._closing = True
        self.mouse.stop()
        self._hide_drawing_controls()
        self._finish_close()

    def _finish_close(self):
        if self.drawing_thread and self.drawing_thread.is_alive():
            self.after(20, self._finish_close)
        else:
            self.destroy()


if __name__ == "__main__":
    logging.basicConfig(handlers=[logging.FileHandler(
                            application_data_directory(__file__) / "chenghua_debug.log", encoding="utf-8")],
                        level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    App().mainloop()
