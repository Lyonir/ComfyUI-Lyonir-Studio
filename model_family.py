from __future__ import annotations

from .resolution import MODEL_FAMILIES


class LyonirModelFamily:
    """Share one model-family selection with compatible combo inputs."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model_family": (MODEL_FAMILIES, {"default": "auto"})}}

    RETURN_TYPES = (MODEL_FAMILIES,)
    RETURN_NAMES = ("model_family",)
    FUNCTION = "select_family"
    CATEGORY = "Lyonir Studio/Utils"
    DESCRIPTION = (
        "Select a model family once and connect it to Lyonir Resolution and Lyonir Sampler. "
        "This selects the family only; it does not load or replace a model. "
        "Choose an explicit family when sharing resolution alignment across nodes."
    )

    def select_family(self, model_family):
        if model_family not in MODEL_FAMILIES:
            raise ValueError(f"Unsupported model family: {model_family!r}")
        return (model_family,)
