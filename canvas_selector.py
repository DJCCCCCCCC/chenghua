from __future__ import annotations

import ctypes
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from drawing_core import desktop_bounds
from image_processing import render_strokes


class CanvasSelector(tk.Toplevel):
    def __init__(self, parent, strokes, image_size, keep_aspect=False):
        super().__init__(parent)
        self.withdraw()
        self.result = None
        self.selection = None
        self.start = None
        self.strokes = strokes
        self.image_size = image_size
        self.keep_aspect = keep_aspect
        self.preview_photo = None
        self.preview_timer = None
        self.bounds = desktop_bounds()
        left, top, width, height = self.bounds
        self.title("选择游戏画布")
        self.overrideredirect(True)
        self.geometry(f"{width}x{height}+0+0")
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.55)
        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._drag)
        self.bind("<Return>", self.confirm)
        self.bind("<KP_Enter>", self.confirm)
        self.bind("<Escape>", self.cancel)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.info = self.canvas.create_text(
            20 - left, 65 - top, anchor="nw", fill="white",
            font=("Microsoft YaHei UI", 12), text="拖动画布范围，然后点击“确定画布区域”"
        )
        toolbar = ttk.Frame(self, style="White.TFrame", padding=8)
        ttk.Button(toolbar, text="确定画布区域", style="Accent.TButton", command=self.confirm).pack(side="left", padx=4)
        ttk.Button(toolbar, text="取消", command=self.cancel).pack(side="left", padx=4)
        toolbar.place(x=20 - left, y=20 - top)
        self.deiconify()
        self.update_idletasks()
        # Set physical coordinates explicitly; Tk's negative offsets are relative.
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_uint]
        hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
        user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), left, top, width, height, 0x0040)
        self.focus_force()
        self.grab_set()

    def _point(self, event):
        return (min(self.bounds[2] - 1, max(0, event.x)),
                min(self.bounds[3] - 1, max(0, event.y)))

    def _press(self, event):
        self.start = self._point(event)
        self.selection = None
        self.canvas.delete("region")
        self.canvas.delete("preview")
        self.canvas.itemconfigure(self.info, text="拖动画布范围，然后点击“确定画布区域”")

    def _drag(self, event):
        if self.start is None:
            return
        x, y = self._point(event)
        sx, sy = self.start
        x0, y0, width, height = min(x, sx), min(y, sy), abs(x - sx), abs(y - sy)
        self.selection = x0, y0, width, height
        self.canvas.delete("region")
        self.canvas.create_rectangle(x0, y0, x0 + width, y0 + height,
                                     outline="#ff6b6b", width=2, tags="region")
        self.canvas.itemconfigure(
            self.info, text=f"X {x0 + self.bounds[0]}   Y {y0 + self.bounds[1]}   {width} × {height}"
        )
        if self.preview_timer is None:
            self.preview_timer = self.after(80, self._render_preview)

    def _render_preview(self):
        if self.preview_timer is not None:
            self.after_cancel(self.preview_timer)
        self.preview_timer = None
        self.canvas.delete("preview")
        if not self.selection:
            return
        x, y, width, height = self.selection
        if width <= 10 or height <= 10:
            return
        image = render_strokes(self.strokes, self.image_size, (width, height),
                               self.keep_aspect, transparent=True)
        self.preview_photo = ImageTk.PhotoImage(image, master=self)
        self.canvas.create_image(x, y, image=self.preview_photo, anchor="nw", tags="preview")
        self.canvas.tag_lower("preview", "region")

    def confirm(self, event=None):
        if not self.selection or min(self.selection[2:]) <= 10:
            self.canvas.itemconfigure(self.info, text="区域宽和高必须大于 10 像素")
            return
        x, y, width, height = self.selection
        self.result = x + self.bounds[0], y + self.bounds[1], width, height
        self._close()

    def cancel(self, event=None):
        self.result = None
        self._close()

    def _close(self):
        if self.preview_timer is not None:
            self.after_cancel(self.preview_timer)
            self.preview_timer = None
        self.grab_release()
        self.destroy()
