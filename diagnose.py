"""Run with ComfyUI's embedded Python for a quick compatibility report."""

import inspect
import sys

print("Python:", sys.version)

try:
    import transformers
    from transformers.masking_utils import (
        create_causal_mask,
        create_sliding_window_causal_mask,
    )
    print("Transformers:", transformers.__version__)
    print("create_causal_mask:", inspect.signature(create_causal_mask))
    print(
        "create_sliding_window_causal_mask:",
        inspect.signature(create_sliding_window_causal_mask),
    )
except Exception as e:
    print("Transformers diagnostic failed:", repr(e))

try:
    import torch
    print("PyTorch:", torch.__version__)
    print("CUDA available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
except Exception as e:
    print("PyTorch diagnostic failed:", repr(e))

try:
    import huggingface_hub
    print("huggingface_hub:", huggingface_hub.__version__)
except Exception as e:
    print("huggingface_hub unavailable:", repr(e))

print("PT-BR repo: acidente/fala_pb_checkpoints")
print("PT-BR default checkpoint: QwenTTS/checkpoint-step-015000")
print("PT-BR runtime speaker: pb_sotaque")
print("PT-BR runtime language: portuguese")
