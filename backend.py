from __future__ import annotations

import gc
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import torch

try:
    import folder_paths
except Exception:
    folder_paths = None

from .compat import apply_transformers_compat

_MODEL_CACHE: Dict[Tuple[Any, ...], Any] = {}
_BACKEND_ROOT: Optional[Path] = None


_SAGE_ORIGINAL_SDPA = None
_SAGE_PATCH_ACTIVE = False


def _restore_sdpa_if_needed():
    global _SAGE_ORIGINAL_SDPA, _SAGE_PATCH_ACTIVE
    if not _SAGE_PATCH_ACTIVE:
        return
    try:
        import torch.nn.functional as F
        if _SAGE_ORIGINAL_SDPA is not None:
            F.scaled_dot_product_attention = _SAGE_ORIGINAL_SDPA
    except Exception:
        pass
    _SAGE_PATCH_ACTIVE = False


def _enable_sage_attention_if_possible() -> bool:
    """Best-effort SageAttention activation with safe fallback to SDPA.

    We intentionally avoid hard pinning against one exact sageattention API.
    If a compatible callable is found, we patch torch's SDPA entry point so the
    existing Qwen stack can keep using attn_implementation='sdpa'. If anything
    fails, we simply return False and the caller falls back to SDPA.
    """
    global _SAGE_ORIGINAL_SDPA, _SAGE_PATCH_ACTIVE

    try:
        import torch.nn.functional as F
    except Exception:
        return False

    if _SAGE_PATCH_ACTIVE:
        return True

    sage_fn = None
    candidates = [
        ('sageattention', 'sageattn'),
        ('sageattention.core', 'sageattn'),
        ('sageattention.sageattn', 'sageattn'),
    ]
    for module_name, attr_name in candidates:
        try:
            mod = __import__(module_name, fromlist=[attr_name])
            fn = getattr(mod, attr_name, None)
            if callable(fn):
                sage_fn = fn
                break
        except Exception:
            continue

    if sage_fn is None:
        return False

    if _SAGE_ORIGINAL_SDPA is None:
        _SAGE_ORIGINAL_SDPA = F.scaled_dot_product_attention

    def _patched_sdpa(query, key, value, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None, enable_gqa=False):
        # Fall back when a feature is requested that the external SageAttention
        # callable may not support.
        if attn_mask is not None or float(dropout_p or 0.0) != 0.0 or bool(enable_gqa):
            return _SAGE_ORIGINAL_SDPA(
                query, key, value,
                attn_mask=attn_mask,
                dropout_p=dropout_p,
                is_causal=is_causal,
                scale=scale,
                enable_gqa=enable_gqa,
            )

        call_attempts = [
            lambda: sage_fn(query, key, value, is_causal=is_causal, scale=scale),
            lambda: sage_fn(query, key, value, is_causal=is_causal),
            lambda: sage_fn(query, key, value),
        ]
        for attempt in call_attempts:
            try:
                result = attempt()
                if result is not None:
                    return result
            except TypeError:
                continue
            except Exception:
                break

        return _SAGE_ORIGINAL_SDPA(
            query, key, value,
            attn_mask=attn_mask,
            dropout_p=dropout_p,
            is_causal=is_causal,
            scale=scale,
            enable_gqa=enable_gqa,
        )

    try:
        F.scaled_dot_product_attention = _patched_sdpa
        _SAGE_PATCH_ACTIVE = True
        return True
    except Exception:
        return False


MODEL_IDS = {
    ("Base", "0.6B"): "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    ("Base", "1.7B"): "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    ("VoiceDesign", "1.7B"): "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    ("CustomVoice", "0.6B"): "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
    ("CustomVoice", "1.7B"): "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
}

# Real Qwen3-TTS fine-tune trained on Brazilian Portuguese (Paraiba accent).
# The upstream model card states that each checkpoint is a complete HF-format model.
PTBR_REPO_ID = "acidente/fala_pb_checkpoints"
PTBR_CHECKPOINTS = {
    "15000": "QwenTTS/checkpoint-step-015000",
    "10000": "QwenTTS/checkpoint-step-010000",
    "5000": "QwenTTS/checkpoint-step-005000",
}
PTBR_SPEAKER = "pb_sotaque"
PTBR_LANGUAGE = "portuguese"


def _custom_nodes_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _candidate_backend_roots():
    """
    Search sibling custom-node folders for the vendored qwen_tts backend from
    flybirdxx/ComfyUI-Qwen-TTS. This avoids pip-installing qwen-tts, whose
    package metadata may pin a different Transformers version.
    """
    base = _custom_nodes_dir()
    preferred = [
        "qwen3-tts-comfyui",
        "ComfyUI-Qwen-TTS",
        "comfyui-qwen-tts",
        "Qwen3-TTS-ComfyUI",
    ]

    seen = set()
    for name in preferred:
        p = base / name
        if p not in seen:
            seen.add(p)
            yield p

    try:
        for p in base.iterdir():
            if not p.is_dir() or p == Path(__file__).resolve().parent:
                continue
            if p in seen:
                continue
            if (p / "qwen_tts" / "inference" / "qwen3_tts_model.py").exists():
                seen.add(p)
                yield p
    except Exception:
        pass


def ensure_backend():
    global _BACKEND_ROOT

    try:
        import qwen_tts  # noqa: F401
    except Exception:
        found = None
        for root in _candidate_backend_roots():
            if (root / "qwen_tts" / "inference" / "qwen3_tts_model.py").exists():
                found = root
                break

        if found is not None:
            sys.path.insert(0, str(found))
            _BACKEND_ROOT = found
        else:
            try:
                import qwen_tts  # noqa: F401
            except Exception as e:
                raise RuntimeError(
                    "Qwen3-TTS backend not found.\n\n"
                    "Keep flybirdxx/ComfyUI-Qwen-TTS installed (it provides the "
                    "vendored qwen_tts backend), or provide an existing qwen_tts "
                    "package without changing your Transformers version."
                ) from e

    # Load the Qwen modules first, then patch only their copied mask functions.
    from qwen_tts import Qwen3TTSModel
    report = apply_transformers_compat()
    return Qwen3TTSModel, report


def get_backend_root() -> Optional[str]:
    if _BACKEND_ROOT:
        return str(_BACKEND_ROOT)
    try:
        import qwen_tts
        return str(Path(qwen_tts.__file__).resolve().parent.parent)
    except Exception:
        return None


def resolve_device(device: str) -> str:
    if device != "auto":
        if device == "cuda":
            return "cuda:0"
        return device

    if torch.cuda.is_available():
        return "cuda:0"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def resolve_dtype(precision: str):
    if precision == "fp32":
        return torch.float32
    if precision == "fp16":
        return torch.float16
    return torch.bfloat16


def _registered_model_roots():
    roots = []
    if folder_paths is not None:
        try:
            roots.append(Path(folder_paths.models_dir) / "qwen-tts")
        except Exception:
            pass

        try:
            for p in folder_paths.get_folder_paths("qwen-tts") or []:
                roots.append(Path(p))
        except Exception:
            pass

    # Fallback for diagnostics outside a fully initialized ComfyUI process.
    if not roots:
        here = Path(__file__).resolve()
        # custom_nodes/Pack/backend.py -> ComfyUI/models/qwen-tts
        try:
            roots.append(here.parents[2] / "models" / "qwen-tts")
        except Exception:
            pass

    unique = []
    seen = set()
    for p in roots:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _is_model_dir(p: Path) -> bool:
    return p.is_dir() and (p / "config.json").exists()


def resolve_model_source(model_type: str, family: str, custom_model_path: str = "") -> str:
    if custom_model_path and custom_model_path.strip():
        p = Path(custom_model_path.strip()).expanduser()
        if not _is_model_dir(p):
            raise RuntimeError(f"Custom model path is not a valid Qwen3-TTS model folder: {p}")
        return str(p)

    key = (model_type, family)
    if key not in MODEL_IDS:
        raise RuntimeError(f"Unsupported model combination: {model_type} / {family}")

    repo_id = MODEL_IDS[key]
    folder_name = repo_id.split("/")[-1]

    candidates = []
    for root in _registered_model_roots():
        candidates.extend([
            root / folder_name,
            root / repo_id.replace("/", "--"),
            root / repo_id.replace("/", "_"),
        ])

    for p in candidates:
        if _is_model_dir(p):
            return str(p)

    return repo_id


def _ptbr_local_candidates(step: str):
    subfolder = PTBR_CHECKPOINTS[step]
    checkpoint_name = Path(subfolder).name
    for root in _registered_model_roots():
        yield root / "Lyonir-PTBR-PB" / checkpoint_name
        yield root / "fala_pb_checkpoints" / subfolder
        yield root / checkpoint_name


def _ptbr_download_root() -> Path:
    roots = _registered_model_roots()
    if not roots:
        raise RuntimeError("Could not determine ComfyUI/models/qwen-tts directory.")
    root = roots[0] / "fala_pb_checkpoints"
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_ptbr_checkpoint(
    checkpoint_step: str = "15000",
    download_if_missing: bool = True,
    custom_model_path: str = "",
) -> str:
    """
    Resolve a complete PT-BR Qwen3-TTS checkpoint to a local directory.

    Qwen3TTSModel.from_pretrained loads AutoModel and AutoProcessor separately;
    because the public PT-BR model lives in a subfolder of a larger HF repo,
    this function snapshots only that subfolder locally and then loads it as a
    normal local HF model directory.
    """
    step = str(checkpoint_step).strip()
    if step not in PTBR_CHECKPOINTS:
        raise RuntimeError(f"Unknown PT-BR checkpoint step: {checkpoint_step}")

    if custom_model_path and custom_model_path.strip():
        p = Path(custom_model_path.strip()).expanduser()
        if not _is_model_dir(p):
            raise RuntimeError(
                f"PT-BR custom_model_path is not a complete Qwen3-TTS checkpoint: {p}"
            )
        return str(p)

    for p in _ptbr_local_candidates(step):
        if _is_model_dir(p):
            return str(p)

    if not download_if_missing:
        expected = next(_ptbr_local_candidates(step), None)
        raise RuntimeError(
            "Brazilian Portuguese checkpoint was not found locally. "
            "Enable 'download_if_missing' for the first run, or set "
            f"custom_model_path to the extracted {PTBR_CHECKPOINTS[step]} folder. "
            f"Suggested local location: {expected}"
        )

    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        raise RuntimeError(
            "huggingface_hub is required to download the PT-BR checkpoint. "
            "It is normally installed together with Transformers."
        ) from e

    subfolder = PTBR_CHECKPOINTS[step]
    repo_root = _ptbr_download_root()

    print(
        "[Lyonir Qwen3-TTS] PT-BR checkpoint not found locally.\n"
        f"[Lyonir Qwen3-TTS] Downloading {PTBR_REPO_ID}/{subfolder}. "
        "This is a large model and the first download may take a while."
    )

    try:
        snapshot_download(
            repo_id=PTBR_REPO_ID,
            allow_patterns=[f"{subfolder}/*", f"{subfolder}/**"],
            local_dir=str(repo_root),
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to download PT-BR checkpoint from {PTBR_REPO_ID}/{subfolder}: {e}"
        ) from e

    downloaded = repo_root / subfolder
    if not _is_model_dir(downloaded):
        raise RuntimeError(
            "PT-BR download finished but a complete model folder was not found at "
            f"{downloaded}. Check the terminal for Hugging Face download errors."
        )

    return str(downloaded)


def _attention_value(attention: str) -> Optional[str]:
    if attention == "auto":
        return None
    if attention == "flash_attention_2":
        return "flash_attention_2"
    if attention == "sage_attention":
        return "sdpa"
    if attention in ("sdpa", "eager"):
        return attention
    return None


def unload_all():
    global _MODEL_CACHE
    _MODEL_CACHE.clear()
    _restore_sdpa_if_needed()
    gc.collect()
    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        except Exception:
            pass


def _load_from_source(
    source: str,
    cache_namespace: str,
    device: str,
    precision: str,
    attention: str,
):
    Qwen3TTSModel, _ = ensure_backend()

    resolved_device = resolve_device(device)
    dtype = resolve_dtype(precision)

    cache_key = (
        cache_namespace,
        source,
        resolved_device,
        str(dtype),
        attention,
    )
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    unload_all()

    kwargs = {
        "device_map": resolved_device,
        "dtype": dtype,
    }

    if attention == "sage_attention":
        if _enable_sage_attention_if_possible():
            print("[Lyonir Studio] SageAttention enabled for Qwen3-TTS.")
        else:
            print("[Lyonir Studio] SageAttention not available; falling back to SDPA.")
    else:
        _restore_sdpa_if_needed()

    attn_impl = _attention_value(attention)
    if attn_impl:
        kwargs["attn_implementation"] = attn_impl

    print(
        f"[Lyonir Qwen3-TTS] Loading {cache_namespace} from {source} "
        f"| device={resolved_device} | dtype={dtype} | attention={attention}"
    )

    try:
        model = Qwen3TTSModel.from_pretrained(source, **kwargs)
    except Exception as first_error:
        if attn_impl == "flash_attention_2":
            print(
                "[Lyonir Qwen3-TTS] flash_attention_2 unavailable; "
                "falling back to SDPA."
            )
            kwargs["attn_implementation"] = "sdpa"
            try:
                model = Qwen3TTSModel.from_pretrained(source, **kwargs)
            except Exception:
                raise first_error
        else:
            raise

    _MODEL_CACHE[cache_key] = model
    return model


def load_model(
    model_type: str,
    family: str,
    device: str,
    precision: str,
    attention: str,
    custom_model_path: str = "",
):
    source = resolve_model_source(model_type, family, custom_model_path)
    return _load_from_source(
        source=source,
        cache_namespace=f"{model_type}-{family}",
        device=device,
        precision=precision,
        attention=attention,
    )


def load_ptbr_model(
    checkpoint_step: str,
    device: str,
    precision: str,
    attention: str,
    download_if_missing: bool = True,
    custom_model_path: str = "",
):
    source = ensure_ptbr_checkpoint(
        checkpoint_step=checkpoint_step,
        download_if_missing=download_if_missing,
        custom_model_path=custom_model_path,
    )
    return _load_from_source(
        source=source,
        cache_namespace=f"PTBR-PB-{checkpoint_step}",
        device=device,
        precision=precision,
        attention=attention,
    )
