from __future__ import annotations

import torch
import torch.nn.functional as F


class LyonirMaskBlur:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mask": ("MASK",),
            "radius": ("INT", {
                "default": 8, "min": 0, "max": 128, "step": 1,
                "tooltip": "Gaussian blur radius in pixels. Zero keeps the original mask.",
            }),
        }}

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "blur_mask"
    CATEGORY = "Lyonir Studio/Image"
    DESCRIPTION = "Softens mask edges with Gaussian blur. Accepts standard ComfyUI masks and batches. Radius zero bypasses blur."

    def blur_mask(self, mask, radius=8):
        if not torch.is_tensor(mask) or mask.ndim not in (2, 3):
            raise ValueError("Lyonir Mask Blur expects a MASK shaped [height, width] or [batch, height, width].")
        if any(size == 0 for size in mask.shape):
            raise ValueError("Lyonir Mask Blur requires a non-empty mask.")
        radius = int(radius)
        if not 0 <= radius <= 128:
            raise ValueError("Lyonir Mask Blur radius must be between 0 and 128.")
        if radius == 0:
            return (mask,)

        # Float32 also supports half-precision masks on CPU without quantization.
        values = mask.to(dtype=torch.float32)
        if mask.ndim == 2:
            values = values.unsqueeze(0)
        values = values.unsqueeze(1)
        sigma = max(radius / 3.0, 0.5)
        positions = torch.arange(-radius, radius + 1, device=mask.device, dtype=torch.float32)
        kernel = torch.exp(-0.5 * (positions / sigma).square())
        kernel = kernel / kernel.sum()

        # Replicate padding supports even a one-pixel image and large radii.
        values = F.conv2d(
            F.pad(values, (radius, radius, 0, 0), mode="replicate"),
            kernel.reshape(1, 1, 1, -1),
        )
        values = F.conv2d(
            F.pad(values, (0, 0, radius, radius), mode="replicate"),
            kernel.reshape(1, 1, -1, 1),
        )
        result = values.squeeze(1).clamp(0, 1)
        if mask.ndim == 2:
            result = result.squeeze(0)
        if mask.is_floating_point():
            result = result.to(dtype=mask.dtype)
        return (result,)
