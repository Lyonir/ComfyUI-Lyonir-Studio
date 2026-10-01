from __future__ import annotations

import math


MODEL_FAMILIES = ["auto", "minimax", "ltx", "bernini", "wan"]


def _alignment_for_family(family: str) -> int:
    family = str(family).lower()
    # LTX video latents are spatially compressed 32x. Current LTX IC-LoRA
    # workflows may use reference_downscale_factor / latent_downscale_factor=2,
    # which requires BOTH latent spatial dimensions to be divisible by 2.
    # Therefore the pixel-space native canvas must be divisible by 64.
    # Keeping LTX on a 64px grid also matches the resolution guidance used by
    # official LTX workflows. Other supported families retain the proven 32px
    # behavior so the MiniMax v2.8 sampling/resolution path is not changed.
    if family == "ltx":
        return 64
    return 32


def _native_size(value: int, family: str) -> int:
    value = int(value)
    alignment = _alignment_for_family(family)
    return max(alignment, int(math.ceil(value / float(alignment)) * alignment))


class LyonirResolutionInt(int):
    """INT-compatible value carrying native and exact requested sizes.

    Upstream latent/video nodes see the numeric/native value. Lyonir Sampler
    reads requested_value and crops the decoded result back to the exact final
    resolution.
    """

    def __new__(cls, native_value: int, requested_value: int, family: str = "auto"):
        obj = int.__new__(cls, int(native_value))
        obj.requested_value = int(requested_value)
        obj.native_value = int(native_value)
        obj.model_family = str(family)
        obj.alignment = _alignment_for_family(family)
        return obj


class LyonirResolution:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {"default": 1920, "min": 1, "max": 16384, "step": 1}),
                "height": ("INT", {"default": 1080, "min": 1, "max": 16384, "step": 1}),
                "model_family": (MODEL_FAMILIES, {"default": "auto"}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "get_resolution"
    CATEGORY = "Lyonir Studio/Utils"
    DESCRIPTION = (
        "Choose the exact FINAL resolution once. The node still has only two outputs: width and height. "
        "For supported video models it sends a safe native canvas upstream (for example LTX 720 -> 768), "
        "while carrying the exact requested size internally so Lyonir Sampler can hard-crop back to the requested output. "
        "No resize/upscale is performed by this node."
    )

    def get_resolution(self, width, height, model_family):
        width = int(width)
        height = int(height)
        family = str(model_family).lower()
        return (
            LyonirResolutionInt(_native_size(width, family), width, family),
            LyonirResolutionInt(_native_size(height, family), height, family),
        )
