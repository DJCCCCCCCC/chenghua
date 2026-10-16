from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from drawing_core import Stroke, fit_area, map_stroke

try:
    import cv2
except ImportError:
    cv2 = None

RESAMPLE_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS


def render_strokes(strokes, image_size, size, keep_aspect=False, transparent=False):
    image = Image.new("RGBA" if transparent else "RGB", size,
                      (0, 0, 0, 0) if transparent else "white")
    draw = ImageDraw.Draw(image)
    area = fit_area(image_size, (0, 0, *size), keep_aspect)
    for stroke in strokes:
        if len(stroke) >= 2:
            draw.line(map_stroke(stroke, image_size, area),
                      fill=(20, 220, 90, 255) if transparent else "black", width=1)
    return image


class ImageProcessor:
    """Reconstructed local Canny/contour path; never imports the original bytecode."""

    def __init__(self, image_path):
        self.image_path = str(image_path)
        with Image.open(self.image_path) as source:
            rgba = ImageOps.exif_transpose(source).convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            self.original = Image.alpha_composite(background, rgba).convert("RGB")
        self.edges = None
        self.strokes: list[Stroke] = []
        self.processed = False

    @property
    def size(self):
        return self.original.size

    @staticmethod
    def _require_opencv():
        if cv2 is None:
            raise RuntimeError("城画缺少 OpenCV，请使用 start_chenghua.cmd 启动，或安装 requirements.txt。")

    def preprocess(self, blur_kernel=7, threshold1=50, threshold2=150):
        self._require_opencv()
        self.processed = False
        self.strokes = []
        kernel = max(1, int(blur_kernel)) | 1
        gray = cv2.cvtColor(np.asarray(self.original), cv2.COLOR_RGB2GRAY)
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (kernel, kernel), 0)
        median = float(np.median(blurred))
        otsu, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        low = max(10, min(int(median * 0.5), int(otsu * 0.5), int(threshold1)))
        high = max(50, min(200, int(median), int(otsu), int(threshold2)))
        edges = cv2.Canny(blurred, low, high)
        if cv2.countNonZero(edges) < 500:
            low, high = max(5, int(low * 0.3)), int(high * 0.5)
            edges = cv2.Canny(blurred, low, high)
            if cv2.countNonZero(edges) < 100:
                low, high = 5, 30
                edges = cv2.Canny(blurred, low, high)
        self.thresholds = low, high
        self.edges = edges
        return Image.fromarray(255 - edges)

    def extract_strokes(self, min_length=20, simplify=0, human_order=True):
        self._require_opencv()
        if self.edges is None:
            self.preprocess()
        contours, _ = cv2.findContours(self.edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        contours = [c for c in contours if cv2.arcLength(c, False) > min_length and len(c) >= 2]
        contours.sort(key=lambda c: cv2.arcLength(c, False), reverse=True)
        strokes = []
        for contour in contours:
            if simplify > 0:
                contour = cv2.approxPolyDP(contour, float(simplify), False)
            points = [(int(x), int(y)) for x, y in contour.reshape(-1, 2)]
            if len(points) > 1:
                strokes.append(points)
        if human_order:
            # Original vertical zones followed by (start_y, start_x) have this same order.
            strokes.sort(key=lambda s: (s[0][1], s[0][0]))
        else:
            strokes.sort(key=len, reverse=True)
        self.strokes = strokes
        self.processed = True
        return strokes

    def preview(self, max_size=(760, 560)):
        if not self.processed:
            self.extract_strokes()
        scale = min(1.0, max_size[0] / self.size[0], max_size[1] / self.size[1])
        size = (max(1, round(self.size[0] * scale)), max(1, round(self.size[1] * scale)))
        return render_strokes(self.strokes, self.size, size)

    def sharpen_strokes(self, strength=10):
        self._require_opencv()
        epsilon = max(0.1, strength / 10.0)
        result = []
        for stroke in self.strokes:
            contour = np.array(stroke, dtype=np.int32).reshape(-1, 1, 2)
            simplified = cv2.approxPolyDP(contour, epsilon, False)
            points = [(int(x), int(y)) for x, y in simplified.reshape(-1, 2)]
            if len(points) >= 2:
                result.append(points)
        self.strokes = result
        return result
