from __future__ import annotations

import inspect
import importlib
import sys
from typing import Callable, Dict, Any

_PATCHED = False
_REPORT = {}


def _signature_info(func: Callable) -> Dict[str, Any]:
    try:
        sig = inspect.signature(func)
        params = sig.parameters
        return {
            "signature": str(sig),
            "params": set(params.keys()),
            "has_var_kw": any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            ),
        }
    except Exception:
        return {"signature": "<unknown>", "params": set(), "has_var_kw": True}


def _make_mask_adapter(raw_func: Callable, label: str) -> Callable:
    """
    Accepts either the Transformers 4.x mask API:
        input_embeds + cache_position
    or the newer API:
        inputs_embeds + position_ids

    The adapter determines the *actual installed function signature* at runtime.
    """
    info = _signature_info(raw_func)
    accepted = info["params"]
    has_var_kw = info["has_var_kw"]

    def adapter(**kwargs):
        kw = dict(kwargs)

        # Transformers 4.57.x uses input_embeds.
        if "input_embeds" in accepted:
            if "input_embeds" not in kw and "inputs_embeds" in kw:
                kw["input_embeds"] = kw.pop("inputs_embeds")
        # Newer Transformers uses inputs_embeds.
        elif "inputs_embeds" in accepted:
            if "inputs_embeds" not in kw and "input_embeds" in kw:
                kw["inputs_embeds"] = kw.pop("input_embeds")

        # Old API requires cache_position.
        if "cache_position" in accepted:
            if "cache_position" not in kw:
                pos = kw.get("position_ids")
                if pos is not None:
                    try:
                        kw["cache_position"] = pos[0] if getattr(pos, "ndim", 0) > 1 else pos
                    except Exception:
                        pass
        else:
            # New API dropped cache_position. Convert to position_ids when needed.
            if "cache_position" in kw:
                cp = kw.get("cache_position")
                if "position_ids" in accepted and "position_ids" not in kw and cp is not None:
                    try:
                        kw["position_ids"] = cp.unsqueeze(0) if getattr(cp, "ndim", 0) == 1 else cp
                    except Exception:
                        kw["position_ids"] = cp
                kw.pop("cache_position", None)

        # Do not pass unsupported kwargs to a strict signature.
        if accepted and not has_var_kw:
            kw = {k: v for k, v in kw.items() if k in accepted}

        return raw_func(**kw)

    adapter.__name__ = f"lyonir_{label}_adapter"
    adapter.__doc__ = f"Lyonir adaptive wrapper around {raw_func!r}"
    adapter._lyonir_mask_adapter = True
    adapter._lyonir_original = raw_func
    adapter._lyonir_signature = info["signature"]
    return adapter


def apply_transformers_compat() -> Dict[str, Any]:
    """
    Patch the Qwen3-TTS vendored modules, NOT Transformers globally.

    This is intentionally scoped so Minimax/LTX/WAN/Qwen-VL and other ComfyUI
    custom nodes continue seeing their normal Transformers functions.
    """
    global _PATCHED, _REPORT

    import transformers
    import transformers.masking_utils as masking_utils

    raw_causal = getattr(
        masking_utils.create_causal_mask,
        "_lyonir_original",
        masking_utils.create_causal_mask,
    )
    raw_sliding = getattr(
        masking_utils.create_sliding_window_causal_mask,
        "_lyonir_original",
        masking_utils.create_sliding_window_causal_mask,
    )

    causal_adapter = _make_mask_adapter(raw_causal, "create_causal_mask")
    sliding_adapter = _make_mask_adapter(raw_sliding, "create_sliding_window_causal_mask")

    patched_modules = []

    # Import the two modules known to contain the problematic local shims.
    known = [
        "qwen_tts.core.models.modeling_qwen3_tts",
        "qwen_tts.core.tokenizer_12hz.modeling_qwen3_tts_tokenizer_v2",
    ]
    for name in known:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue

        if hasattr(mod, "create_causal_mask"):
            mod.create_causal_mask = causal_adapter
        if hasattr(mod, "create_sliding_window_causal_mask"):
            mod.create_sliding_window_causal_mask = sliding_adapter
        patched_modules.append(name)

    # Also patch any already-loaded qwen_tts modules that copied the functions
    # into module-local globals.
    for name, mod in list(sys.modules.items()):
        if not name.startswith("qwen_tts.") or mod is None:
            continue
        changed = False
        if hasattr(mod, "create_causal_mask"):
            try:
                mod.create_causal_mask = causal_adapter
                changed = True
            except Exception:
                pass
        if hasattr(mod, "create_sliding_window_causal_mask"):
            try:
                mod.create_sliding_window_causal_mask = sliding_adapter
                changed = True
            except Exception:
                pass
        if changed and name not in patched_modules:
            patched_modules.append(name)

    causal_info = _signature_info(raw_causal)
    sliding_info = _signature_info(raw_sliding)

    _REPORT = {
        "transformers_version": getattr(transformers, "__version__", "unknown"),
        "create_causal_mask_signature": causal_info["signature"],
        "create_sliding_window_causal_mask_signature": sliding_info["signature"],
        "patched_modules": patched_modules,
    }
    _PATCHED = True

    print(
        "[Lyonir Qwen3-TTS] Transformers "
        f"{_REPORT['transformers_version']} | create_causal_mask"
        f"{_REPORT['create_causal_mask_signature']}"
    )
    print(
        f"[Lyonir Qwen3-TTS] Adaptive mask compatibility active "
        f"({len(patched_modules)} qwen_tts module(s) patched)"
    )

    return dict(_REPORT)


def compatibility_report() -> Dict[str, Any]:
    return dict(_REPORT)
