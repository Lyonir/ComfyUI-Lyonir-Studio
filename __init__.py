"""
ComfyUI-Lyonir-Studio
Unified Lyonir Studio custom node pack with Qwen3-TTS, Image Compare and the complete single-pass MiniMax H3 sampler.
"""

from .nodes import (
    LyonirQwen3TTSVoiceClone,
    LyonirQwen3TTSVoiceDesign,
    LyonirQwen3TTSCustomVoice,
)
from .image_compare import LyonirImageCompare
from .lyonir_sampler import LyonirSampler
from .resolution import LyonirResolution
from .model_family import LyonirModelFamily
from .save_image_gallery import LyonirSaveImage
from .save_video_gallery import LyonirSaveVideo

NODE_CLASS_MAPPINGS = {
    "Lyonir_ModelFamily": LyonirModelFamily,
    "Lyonir_Qwen3TTSVoiceClone": LyonirQwen3TTSVoiceClone,
    "Lyonir_Qwen3TTSVoiceDesign": LyonirQwen3TTSVoiceDesign,
    "Lyonir_Qwen3TTSCustomVoice": LyonirQwen3TTSCustomVoice,
    "Lyonir_ImageCompare": LyonirImageCompare,
    "Lyonir_Sampler": LyonirSampler,
    "Lyonir_Resolution": LyonirResolution,
    "Lyonir_SaveImage": LyonirSaveImage,
    "Lyonir_SaveVideo": LyonirSaveVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Lyonir_ModelFamily": "🐺 Lyonir Model Family",
    "Lyonir_Qwen3TTSVoiceClone": "🐺 Lyonir Qwen3-TTS Voice Clone",
    "Lyonir_Qwen3TTSVoiceDesign": "🐺 Lyonir Qwen3-TTS Voice Design",
    "Lyonir_Qwen3TTSCustomVoice": "🐺 Lyonir Qwen3-TTS Custom Voice",
    "Lyonir_ImageCompare": "🐺 Lyonir Image Compare",
    "Lyonir_Sampler": "🐺 Lyonir Sampler",
    "Lyonir_Resolution": "🐺 Lyonir Resolution",
    "Lyonir_SaveImage": "🐺 Lyonir Save Image",
    "Lyonir_SaveVideo": "🐺 Lyonir Save Video",
}

__version__ = "3.5.18"

print(f"[Lyonir Studio] v{__version__} loaded")


# Frontend widgets (Nodes 2.0 compatible DOM UI).
WEB_DIRECTORY = "./web"
