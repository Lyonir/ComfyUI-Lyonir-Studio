from __future__ import annotations

import math
from typing import Optional

import torch

from .progress_utils import make_progress, update_progress


CROP_ANCHORS = [
    "center", "top", "bottom", "left", "right",
    "top_left", "top_right", "bottom_left", "bottom_right",
]
MODEL_FAMILIES = ["auto", "minimax", "ltx", "bernini", "wan"]
NOISE_MODES = ["enabled", "disabled"]

try:
    import comfy.samplers as _comfy_samplers
    SAMPLER_NAMES = list(getattr(_comfy_samplers.KSampler, "SAMPLERS", [])) or ["res_multistep"]
    SCHEDULER_NAMES = list(getattr(_comfy_samplers.KSampler, "SCHEDULERS", [])) or ["simple", "normal", "beta"]
except Exception:
    SAMPLER_NAMES = ["res_multistep"]
    SCHEDULER_NAMES = ["simple", "normal", "beta"]

if "res_multistep" in SAMPLER_NAMES:
    SAMPLER_NAMES.remove("res_multistep")
SAMPLER_NAMES.insert(0, "res_multistep")
if "simple" in SCHEDULER_NAMES:
    SCHEDULER_NAMES.remove("simple")
SCHEDULER_NAMES.insert(0, "simple")


def _requested_size(value) -> int:
    return int(getattr(value, "requested_value", int(value)))


def _native_size_from_value(value) -> int:
    return int(getattr(value, "native_value", int(value)))

def _has_resolution_metadata(value) -> bool:
    return hasattr(value, "requested_value") and hasattr(value, "native_value")


def _ltx_video_latent_size(latent: dict):
    """Return approximate decoded (width, height) for the video part of an LTX AV latent."""
    if not isinstance(latent, dict) or "samples" not in latent:
        return None
    samples = latent["samples"]
    parts = _nested_parts(samples)
    video = parts[0] if parts else samples
    if not torch.is_tensor(video) or video.ndim != 5:
        return None
    # LTX-2 video latent is spatially compressed 32x.
    return int(video.shape[-1]) * 32, int(video.shape[-2]) * 32


def _validate_ltx_canvas(latent: dict, target_width, target_height):
    size = _ltx_video_latent_size(latent)
    if size is None:
        return None
    actual_w, actual_h = size
    requested_w = _requested_size(target_width)
    requested_h = _requested_size(target_height)
    native_w = _native_size_from_value(target_width)
    native_h = _native_size_from_value(target_height)

    if actual_w < requested_w or actual_h < requested_h:
        if not (_has_resolution_metadata(target_width) and _has_resolution_metadata(target_height)):
            raise RuntimeError(
                f"LTX latent canvas is {actual_w}x{actual_h}, but final output is {requested_w}x{requested_h}. "
                "Connect the two outputs of 🐺 Lyonir Resolution to BOTH EmptyLTXVLatentVideo width/height and "
                "Lyonir Sampler target_width/target_height. For 720x1280, Lyonir Resolution will send 768x1280 "
                "to LTX while preserving 720x1280 as the final hard-crop target. No upscale is used."
            )
        raise RuntimeError(
            f"LTX latent canvas is {actual_w}x{actual_h}, smaller than the requested final {requested_w}x{requested_h}. "
            f"Expected native canvas {native_w}x{native_h}. Check that 🐺 Lyonir Resolution is connected "
            "to the latent-creation node, not only to Lyonir Sampler."
        )

    if _has_resolution_metadata(target_width) and _has_resolution_metadata(target_height):
        if actual_w != native_w or actual_h != native_h:
            raise RuntimeError(
                f"LTX latent canvas is {actual_w}x{actual_h}, but 🐺 Lyonir Resolution requested native "
                f"{native_w}x{native_h} for final {requested_w}x{requested_h}. Connect the same Resolution width/height "
                "outputs to EmptyLTXVLatentVideo and Lyonir Sampler."
            )
    return actual_w, actual_h


def _nested_parts(samples):
    if getattr(samples, "is_nested", False):
        if hasattr(samples, "tensors"):
            return list(samples.tensors)
        if hasattr(samples, "unbind"):
            return list(samples.unbind())
    return None


def _crop_offsets(full_w: int, full_h: int, target_w: int, target_h: int, anchor: str):
    extra_x = max(0, int(full_w) - int(target_w))
    extra_y = max(0, int(full_h) - int(target_h))
    a = str(anchor)
    if "left" in a or a == "left":
        x = 0
    elif "right" in a or a == "right":
        x = extra_x
    else:
        x = extra_x // 2
    if "top" in a or a == "top":
        y = 0
    elif "bottom" in a or a == "bottom":
        y = extra_y
    else:
        y = extra_y // 2
    return x, y


def _crop_images(images: torch.Tensor, target_w: int, target_h: int, anchor: str) -> torch.Tensor:
    if not torch.is_tensor(images) or images.ndim != 4:
        raise RuntimeError(f"Unexpected decoded image shape: {getattr(images, 'shape', None)}")
    full_h, full_w = int(images.shape[1]), int(images.shape[2])
    if target_w > full_w or target_h > full_h:
        raise RuntimeError(
            f"Decoded frame is {full_w}x{full_h}, smaller than requested {target_w}x{target_h}. "
            "Lyonir Sampler never upscales silently. Use 🐺 Lyonir Resolution upstream so the model generates "
            "a native canvas at least as large as the requested final output, then Lyonir will hard-crop to the exact size."
        )
    x, y = _crop_offsets(full_w, full_h, target_w, target_h, anchor)
    return images[:, y:y + target_h, x:x + target_w, :]


def _model_fingerprint(model) -> str:
    chunks = []
    seen = set()
    objs = [model, getattr(model, "model", None)]
    for key in ("model_sampling", "diffusion_model"):
        try:
            objs.append(model.get_model_object(key))
        except Exception:
            pass
    for obj in objs:
        if obj is None or id(obj) in seen:
            continue
        seen.add(id(obj))
        cls = obj.__class__
        chunks.extend([cls.__name__, cls.__module__])
        for attr in ("model_config", "model_type", "model_name"):
            try:
                value = getattr(obj, attr, None)
                if value is not None:
                    chunks.extend([value.__class__.__name__, value.__class__.__module__, str(value)[:300]])
            except Exception:
                pass
    return " ".join(chunks).lower()


def _detect_family(model, latent: dict, requested: str) -> str:
    requested = str(requested).lower()
    if requested != "auto":
        return requested

    fp = _model_fingerprint(model)
    if "minimax" in fp or "h3" in fp:
        return "minimax"
    if "ltx" in fp:
        return "ltx"
    if "bernini" in fp:
        return "bernini"
    if "wan" in fp:
        return "wan"

    if isinstance(latent, dict) and "samples" in latent:
        parts = _nested_parts(latent["samples"])
        if parts and len(parts) == 2:
            video, audio = parts
            if torch.is_tensor(video) and torch.is_tensor(audio):
                if video.ndim == 5 and int(video.shape[1]) == 24 and audio.ndim == 4 and int(audio.shape[1]) == 32:
                    return "minimax"
                return "ltx"
    return "generic"


def _calculate_sigmas(model, scheduler: str, steps: int, denoise: float):
    import comfy.samplers
    steps = int(steps)
    denoise = float(denoise)
    total_steps = steps
    if denoise < 1.0:
        if denoise <= 0.0:
            return torch.FloatTensor([])
        total_steps = int(steps / denoise)
    sigmas = comfy.samplers.calculate_sigmas(
        model.get_model_object("model_sampling"), str(scheduler), total_steps
    ).cpu()
    return sigmas[-(steps + 1):]


def _prepare_latent(model, latent: dict):
    try:
        import comfy.sample
    except Exception as exc:
        raise RuntimeError("ComfyUI sampling modules are unavailable.") from exc
    if not isinstance(latent, dict) or "samples" not in latent:
        raise ValueError("Lyonir Sampler expects a ComfyUI LATENT dictionary with a 'samples' field.")
    work = dict(latent)
    work["samples"] = comfy.sample.fix_empty_latent_channels(
        model,
        work["samples"],
        work.get("downscale_ratio_spacial", None),
        work.get("downscale_ratio_temporal", None),
    )
    return work


def _build_guider(model, conditioning, negative, cfg: float, force_basic: bool = False):
    import comfy.samplers
    from comfy_extras.nodes_custom_sampler import Guider_Basic

    if force_basic or negative is None:
        guider = Guider_Basic(model)
        guider.set_conds(conditioning)
        return guider, "BasicGuider"

    guider = comfy.samplers.CFGGuider(model)
    guider.set_conds(conditioning, negative)
    guider.set_cfg(float(cfg))
    return guider, "CFGGuider"


def _sample_once(
    model,
    conditioning,
    negative,
    latent,
    seed: int,
    noise_mode: str,
    sampler_name: str,
    sigmas,
    cfg: float,
    force_basic: bool = False,
):
    try:
        import comfy.model_management
        import comfy.samplers
        import comfy.utils
        import latent_preview
        from comfy_extras.nodes_custom_sampler import Noise_EmptyNoise, Noise_RandomNoise
    except Exception as exc:
        raise RuntimeError("Lyonir Sampler requires current ComfyUI custom-sampling modules.") from exc

    work = _prepare_latent(model, latent)
    latent_image = work["samples"]
    noise = Noise_EmptyNoise() if str(noise_mode) == "disabled" else Noise_RandomNoise(int(seed))
    sampler = comfy.samplers.sampler_object(str(sampler_name))
    guider, guider_name = _build_guider(model, conditioning, negative, cfg, force_basic=force_basic)

    if sigmas is None or int(sigmas.numel()) == 0:
        return work, guider_name

    noise_mask = work.get("noise_mask", None)
    x0_output = {}
    callback = latent_preview.prepare_callback(guider.model_patcher, sigmas.shape[-1] - 1, x0_output)
    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
    samples = guider.sample(
        noise.generate_noise(work),
        latent_image,
        sampler,
        sigmas,
        denoise_mask=noise_mask,
        callback=callback,
        disable_pbar=disable_pbar,
        seed=noise.seed,
    )
    samples = samples.to(comfy.model_management.intermediate_device())
    out = dict(work)
    out.pop("downscale_ratio_spacial", None)
    out.pop("downscale_ratio_temporal", None)
    out["samples"] = samples
    return out, guider_name


def _validate_minimax_native_latent(latent: dict, target_width, target_height):
    parts = _nested_parts(latent.get("samples", None)) if isinstance(latent, dict) else None
    if parts is None or len(parts) != 2:
        raise ValueError("MiniMax adapter expects the native MiniMax H3 joint AV latent.")
    video, audio = parts
    if not torch.is_tensor(video) or video.ndim != 5 or int(video.shape[1]) != 24:
        raise ValueError("MiniMax H3 video latent must be [B,24,T,H/16,W/16].")
    if not torch.is_tensor(audio) or audio.ndim != 4 or int(audio.shape[1]) != 32:
        raise ValueError("MiniMax H3 audio latent must be [B,32,2,T].")
    source_width = int(video.shape[-1]) * 16
    source_height = int(video.shape[-2]) * 16
    required_width = _native_size_from_value(target_width)
    required_height = _native_size_from_value(target_height)
    if source_width != required_width or source_height != required_height:
        raise RuntimeError(
            f"MiniMax native latent is {source_width}x{source_height}, expected {required_width}x{required_height}. "
            "Connect the same Lyonir Resolution width/height outputs to MiniMax and Lyonir Sampler."
        )
    return source_width, source_height


def _split_av_latent(sampled_latent: dict):
    if not isinstance(sampled_latent, dict) or "samples" not in sampled_latent:
        return sampled_latent, None
    parts = _nested_parts(sampled_latent["samples"])
    if not parts or len(parts) < 2:
        return sampled_latent, None
    video_latent = dict(sampled_latent)
    audio_latent = dict(sampled_latent)
    video_latent["samples"] = parts[0]
    audio_latent["samples"] = parts[1]
    if "noise_mask" in sampled_latent and sampled_latent["noise_mask"] is not None:
        masks = _nested_parts(sampled_latent["noise_mask"])
        if masks and len(masks) >= 2:
            video_latent["noise_mask"] = masks[0]
            audio_latent["noise_mask"] = masks[1]
    return video_latent, audio_latent


def _conditioning_get_any_value(conditioning, key, default=None):
    """Read one metadata value from a ComfyUI CONDITIONING list."""
    if conditioning is None:
        return default
    try:
        for item in conditioning:
            if isinstance(item, (list, tuple)) and len(item) > 1 and isinstance(item[1], dict):
                if key in item[1]:
                    return item[1][key]
    except Exception:
        pass
    return default


def _ltx_num_keyframes(conditioning, latent_shape) -> int:
    """Mirror ComfyUI LTX get_keyframe_idxs() counting for post-sampling guide cropping."""
    keyframe_idxs = _conditioning_get_any_value(conditioning, "keyframe_idxs", None)
    if keyframe_idxs is None:
        return 0

    try:
        if latent_shape is not None and len(latent_shape) == 5:
            tokens_per_frame = int(latent_shape[-2]) * int(latent_shape[-1])
            if tokens_per_frame > 0:
                return max(0, int(keyframe_idxs.shape[2]) // tokens_per_frame)
    except Exception:
        pass

    entries = _conditioning_get_any_value(conditioning, "guide_attention_entries", None)
    if entries:
        total = 0
        for entry in entries:
            try:
                total += int(entry["latent_shape"][0])
            except Exception:
                continue
        if total > 0:
            return total

    try:
        return int(torch.unique(keyframe_idxs[:, 0, :, 0]).shape[0])
    except Exception:
        return 0


def _crop_ltx_video_guides(video_latent: dict, conditioning):
    """Remove temporary LTX IC-LoRA guide tokens before VAE decode.

    Official LTX IC-LoRA workflows place LTXVCropGuides after sampling. A video
    guide can append an entire latent-length worth of temporary keyframes; decoding
    them as normal video produces the characteristic clean first segment followed by
    severe colored noise. This helper performs the same temporal crop on the video
    stream only; the audio stream is left untouched.
    """
    if not isinstance(video_latent, dict) or "samples" not in video_latent:
        return video_latent, 0

    samples = video_latent["samples"]
    if not torch.is_tensor(samples) or samples.ndim != 5:
        return video_latent, 0

    num_keyframes = _ltx_num_keyframes(conditioning, samples.shape)
    if num_keyframes <= 0:
        return video_latent, 0
    if num_keyframes >= int(samples.shape[2]):
        raise RuntimeError(
            f"LTX guide crop detected {num_keyframes} temporary keyframe latents, "
            f"but the sampled video latent has only {int(samples.shape[2])} temporal slices. "
            "The IC-LoRA conditioning/latent pairing is inconsistent."
        )

    out = dict(video_latent)
    out["samples"] = samples[:, :, :-num_keyframes]

    mask = video_latent.get("noise_mask", None)
    if torch.is_tensor(mask) and mask.ndim == 5 and int(mask.shape[2]) >= num_keyframes:
        out["noise_mask"] = mask[:, :, :-num_keyframes]

    return out, num_keyframes


def _recombine_av_latent(original_latent: dict, video_latent: dict, audio_latent: Optional[dict]):
    """Rebuild a cleaned joint AV latent after LTX guide cropping."""
    if audio_latent is None:
        return video_latent

    try:
        import comfy.nested_tensor
    except Exception as exc:
        raise RuntimeError("Could not rebuild the LTX joint AV latent after guide cropping.") from exc

    out = dict(original_latent)
    out["samples"] = comfy.nested_tensor.NestedTensor(
        (video_latent["samples"], audio_latent["samples"])
    )

    video_mask = video_latent.get("noise_mask", None)
    audio_mask = audio_latent.get("noise_mask", None)
    if video_mask is not None or audio_mask is not None:
        if video_mask is None:
            video_mask = torch.ones_like(video_latent["samples"])
        if audio_mask is None:
            audio_mask = torch.ones_like(audio_latent["samples"])
        out["noise_mask"] = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
    else:
        out.pop("noise_mask", None)

    return out


def _decode_video(video_vae, sampled_latent: dict):
    if video_vae is None:
        return None
    video_latent, _ = _split_av_latent(sampled_latent)
    latent_samples = video_latent["samples"]
    images = video_vae.decode(latent_samples)
    if len(images.shape) == 5:
        images = images.reshape(-1, images.shape[-3], images.shape[-2], images.shape[-1])
    return images


def _decode_audio(audio_vae, sampled_latent: dict):
    if audio_vae is None:
        return None
    _, audio_latent = _split_av_latent(sampled_latent)
    if audio_latent is None:
        return None
    try:
        from comfy_extras.nodes_audio import vae_decode_audio
    except Exception as exc:
        raise RuntimeError("Could not import ComfyUI's native audio VAE decoder.") from exc
    return vae_decode_audio(audio_vae, audio_latent)


def _sample_minimax_v28(model, conditioning, latent, seed, noise, steps, sampler_name, scheduler, denoise):
    """Frozen v2.8 MiniMax path. Do not change without a regression reason."""
    sigmas = _calculate_sigmas(model, scheduler, steps, denoise)
    sampled, guider_name = _sample_once(
        model=model,
        conditioning=conditioning,
        negative=None,
        latent=latent,
        seed=seed,
        noise_mode=noise,
        sampler_name=sampler_name,
        sigmas=sigmas,
        cfg=1.0,
        force_basic=True,
    )
    return sampled, guider_name, "single"


def _sample_generic(
    family,
    model,
    conditioning,
    negative,
    latent,
    seed,
    noise,
    cfg,
    steps,
    sampler_name,
    scheduler,
    denoise,
):
    """Generic single-model custom-sampling path for LTX / Bernini / Wan.

    Unlike earlier experiments, this path intentionally does not support a built-in
    secondary model or split-step logic. If the user wants a second stage, they should
    chain a second Lyonir Sampler node in the workflow.
    """
    sigmas = _calculate_sigmas(model, scheduler, steps, denoise)
    sampled, guider_name = _sample_once(
        model=model,
        conditioning=conditioning,
        negative=negative,
        latent=latent,
        seed=seed,
        noise_mode=noise,
        sampler_name=sampler_name,
        sigmas=sigmas,
        cfg=cfg,
        force_basic=False if family != "minimax" else True,
    )
    return sampled, guider_name, "single"


class LyonirSampler:
    """Multi-model wrapper around ComfyUI's custom-sampling primitives.

    MiniMax H3 keeps the proven v2.8 path. LTX, Bernini-R and Wan use the clean
    single-model custom-sampling path. Chain another Lyonir Sampler for extra stages.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "conditioning": ("CONDITIONING",),
                "latent": ("LATENT",),
                "video_vae": ("VAE",),
                "target_width": ("INT", {"default": 1080, "min": 32, "max": 16384, "step": 1}),
                "target_height": ("INT", {"default": 1080, "min": 32, "max": 16384, "step": 1}),
                "model_family": (MODEL_FAMILIES, {"default": "auto"}),
                "seed": ("INT", {"default": 43, "min": 0, "max": 0xFFFFFFFFFFFFFFFF, "control_after_generate": True}),
                "noise": (NOISE_MODES, {"default": "enabled"}),
                "steps": ("INT", {"default": 20, "min": 1, "max": 10000, "step": 1}),
                "sampler_name": (SAMPLER_NAMES, {"default": "res_multistep"}),
                "scheduler": (SCHEDULER_NAMES, {"default": "simple"}),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "crop_anchor": (CROP_ANCHORS, {"default": "center"}),
            },
            "optional": {
                "negative": ("CONDITIONING",),
                "audio_vae": ("VAE",),
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            },
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "LATENT", "STRING")
    RETURN_NAMES = ("images", "audio", "latent", "info")
    FUNCTION = "generate"
    CATEGORY = "Lyonir Studio/Sampling"
    DESCRIPTION = (
        "Unified SamplerCustomAdvanced-style sampler for MiniMax H3, LTX, Bernini-R and Wan. "
        "Auto detects the family when possible; manual override is available. MiniMax uses the frozen v2.8 BasicGuider path. "
        "Other families use a clean single-model custom-sampling path with optional negative/CFG, built-in video/audio decode, exact hard crop, and native LTX IC-LoRA guide cleanup. "
        "If you want a second stage or another model, chain a second Lyonir Sampler in the workflow instead of using a secondary model inside the node."
    )

    def generate(
        self,
        model,
        conditioning,
        latent,
        video_vae,
        target_width,
        target_height,
        model_family,
        seed,
        noise,
        steps,
        sampler_name,
        scheduler,
        denoise,
        crop_anchor,
        audio_vae=None,
        negative=None,
        cfg=1.0,
    ):
        pbar = make_progress()
        update_progress(pbar, 2)

        requested_width = _requested_size(target_width)
        requested_height = _requested_size(target_height)
        family = _detect_family(model, latent, model_family)
        update_progress(pbar, 8)

        if family == "ltx":
            _validate_ltx_canvas(latent, target_width, target_height)

        if family == "minimax":
            source_width, source_height = _validate_minimax_native_latent(latent, target_width, target_height)
            sampled, guider_name, passes = _sample_minimax_v28(
                model, conditioning, latent, int(seed), str(noise), int(steps), str(sampler_name), str(scheduler), float(denoise)
            )
        else:
            source_width = _native_size_from_value(target_width)
            source_height = _native_size_from_value(target_height)
            sampled, guider_name, passes = _sample_generic(
                family=family,
                model=model,
                conditioning=conditioning,
                negative=negative,
                latent=latent,
                seed=int(seed),
                noise=str(noise),
                cfg=float(cfg),
                steps=int(steps),
                sampler_name=str(sampler_name),
                scheduler=str(scheduler),
                denoise=float(denoise),
            )
        update_progress(pbar, 76)

        ltx_guides_cropped = 0
        sampled_for_decode = sampled
        if family == "ltx":
            ltx_video_latent, ltx_audio_latent = _split_av_latent(sampled)
            ltx_video_latent, ltx_guides_cropped = _crop_ltx_video_guides(
                ltx_video_latent, conditioning
            )
            sampled_for_decode = _recombine_av_latent(
                sampled, ltx_video_latent, ltx_audio_latent
            )
            sampled = sampled_for_decode

        images = _decode_video(video_vae, sampled_for_decode)
        update_progress(pbar, 87)
        if images is not None:
            images = _crop_images(images, requested_width, requested_height, crop_anchor)
        update_progress(pbar, 93)
        audio = _decode_audio(audio_vae, sampled_for_decode)
        update_progress(pbar, 98)

        decoded_w = int(images.shape[2]) if torch.is_tensor(images) and images.ndim == 4 else None
        decoded_h = int(images.shape[1]) if torch.is_tensor(images) and images.ndim == 4 else None
        decoded_frames = int(images.shape[0]) if torch.is_tensor(images) and images.ndim == 4 else None
        sigma_mode = f"scheduler:{scheduler}"
        info = (
            f"Lyonir Sampler | family={family} | requested={requested_width}x{requested_height} | "
            f"input_native_hint={source_width}x{source_height} | decoded_final={decoded_w}x{decoded_h} | "
            f"decoded_frames={decoded_frames} | ltx_guides_cropped={ltx_guides_cropped} | "
            f"guider={guider_name} | cfg={float(cfg):.2f} | steps={int(steps)} | sampler={sampler_name} | "
            f"sigmas={sigma_mode} | denoise={float(denoise):.3f} | noise={noise} | sampling={passes} | "
            "core=ComfyUI_custom_sampling | crop=hard | resize=no | upscale=no"
        )
        update_progress(pbar, 100)
        return images, audio, sampled, info
