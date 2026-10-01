from __future__ import annotations

from nodes import PreviewImage

from .progress_utils import make_progress, update_progress


class LyonirImageCompare(PreviewImage):
    """Interactive A/B image comparer.

    The backend only prepares temporary preview files; the actual comparison is
    rendered by a frontend DOM widget so it works with modern ComfyUI Nodes 2.0.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_a": ("IMAGE",),
                "image_b": ("IMAGE",),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image_a",)
    FUNCTION = "compare_images"
    CATEGORY = "Lyonir Studio/Image"
    OUTPUT_NODE = True

    def compare_images(
        self,
        image_a,
        image_b,
        prompt=None,
        extra_pnginfo=None,
    ):
        pbar = make_progress()
        update_progress(pbar, 3)
        # PreviewImage writes to ComfyUI's temp directory.  Keeping A and B in
        # separate UI fields lets the frontend build an interactive layered view.
        a_ui = self.save_images(
            image_a,
            filename_prefix="lyonir_compare_A",
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
        )["ui"]["images"]
        update_progress(pbar, 50)
        b_ui = self.save_images(
            image_b,
            filename_prefix="lyonir_compare_B",
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
        )["ui"]["images"]

        update_progress(pbar, 100)
        return {
            "ui": {
                "lyonir_compare_a": a_ui,
                "lyonir_compare_b": b_ui,
            },
            # Passthrough output keeps the node usable inside larger / looping
            # graphs while the node itself remains primarily a visual comparer.
            "result": (image_a,),
        }
