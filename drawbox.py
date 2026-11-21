from __future__ import annotations

import json
import math

import numpy as np
import torch
from PIL import Image, ImageDraw
from nodes import PreviewImage


def box_bounds(box, width, height):
    """Convert normalized drag endpoints into a clipped, exclusive pixel box."""
    try:
        values = json.loads(box)
        if values == []:
            return None
        if not isinstance(values, list) or len(values) != 4:
            raise ValueError
        if any(isinstance(value, bool) for value in values):
            raise ValueError
        values = [float(value) for value in values]
        if not all(math.isfinite(value) for value in values):
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("Drawbox selection must contain four finite coordinates.") from None
    x1, y1, x2, y2 = [max(0.0, min(1.0, value)) for value in values]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if left == right or top == bottom:
        return None
    return (
        math.floor(left * width),
        math.floor(top * height),
        min(width, math.ceil(right * width)),
        min(height, math.ceil(bottom * height)),
    )



class LyonirDrawbox(PreviewImage):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "box": ("STRING", {"default": "[]", "multiline": False}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "draw_box"
    CATEGORY = "Lyonir Studio/Image"
    OUTPUT_NODE = True
    DESCRIPTION = "Connect an IMAGE and draw numbered rectangles, ellipses or freehand strokes. Outputs the original image and their combined MASK. Colors and names are saved in the workflow."

    def draw_box(self, image, box="[]", prompt=None, extra_pnginfo=None):
        if not torch.is_tensor(image) or image.ndim != 4 or any(size == 0 for size in image.shape):
            raise ValueError("Lyonir Drawbox expects an IMAGE shaped [batch, height, width, channels].")
        batch, height, width, _ = image.shape
        try:
            selection = json.loads(box)
        except (TypeError, ValueError):
            raise ValueError("Invalid Drawbox selection JSON.") from None
        if isinstance(selection, dict):
            if selection.get("version") != 2 or not isinstance(selection.get("boxes"), list):
                raise ValueError("Invalid Drawbox shapes format.")
            shapes = selection["boxes"]
        else:
            shapes = [{"type": "rect", "coords": selection}]
        surface = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(surface)
        for shape in shapes:
            if not isinstance(shape, dict) or "coords" not in shape:
                raise ValueError("Invalid Drawbox shape.")
            kind = shape.get("type", "rect")
            bounds = box_bounds(json.dumps(shape["coords"]), width, height)
            if kind == "freehand":
                points = shape.get("points")
                thickness = shape.get("width", 0.03)
                if (not isinstance(points, list) or not points
                        or isinstance(thickness, bool) or not isinstance(thickness, (int, float))
                        or not math.isfinite(thickness) or thickness <= 0):
                    raise ValueError("Invalid Drawbox freehand stroke.")
                pixels = []
                for point in points:
                    if (not isinstance(point, list) or len(point) != 2
                            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                   or not math.isfinite(v) for v in point)):
                        raise ValueError("Invalid Drawbox freehand point.")
                    pixels.append((
                        min(width - 1, max(0, round(point[0] * width))),
                        min(height - 1, max(0, round(point[1] * height))),
                    ))
                stroke_width = max(1, round(min(1, thickness) * min(width, height)))
                if len(pixels) > 1:
                    draw.line(pixels, fill=255, width=stroke_width, joint="curve")
                radius = (stroke_width - 1) / 2
                for x, y in pixels:
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
            elif kind in ("rect", "ellipse"):
                if bounds is None:
                    continue
                left, top, right, bottom = bounds
                region = (left, top, right - 1, bottom - 1)
                if kind == "ellipse":
                    draw.ellipse(region, fill=255)
                else:
                    draw.rectangle(region, fill=255)
            else:
                raise ValueError("Unsupported Drawbox shape type.")
        values = np.asarray(surface, dtype=np.float32).copy() / 255.0
        mask = torch.from_numpy(values).to(device=image.device).unsqueeze(0).repeat(batch, 1, 1)
        preview = self.save_images(
            image[:1], filename_prefix="lyonir_drawbox",
            prompt=prompt, extra_pnginfo=extra_pnginfo,
        )["ui"]["images"]
        return {"ui": {"lyonir_drawbox_preview": preview}, "result": (image, mask)}
