"""Lossless Lyonir LATENT crop intent for ComfyUI's standard VAE Decode nodes.

A latent grid cannot represent every pixel resolution exactly: LTX compresses
spatial dimensions 32x. Re-encoding a 720-pixel crop truncates it to 704 px
and alters image details. Instead, return the ORIGINAL sampled latent with a
spatial crop tag, preserved by LTXVSeparateAVLatent, and apply that crop after
VAE decoding. No changes to sampled tensor data, VAE encode, or workflow nodes.

This deliberately patches only ComfyUI's built-in VAEDecode/VAEDecodeTiled
classes. Unmarked latents and all other decoders retain original behavior.
"""
from __future__ import annotations

from functools import wraps
import logging

CROP_KEY = "lyonir_final_pixel_crop"
_LOG = logging.getLogger("LyonirStudio.LatentCrop")


def set_latent_crop(latent, width: int, height: int, anchor: str):
    """Attach the exact intended *decoded* dimensions without modifying latent."""
    if not isinstance(latent, dict) or "samples" not in latent:
        raise ValueError("Cannot tag a LATENT without samples")
    w = int(width)
    h = int(height)
    if not (1 <= w <= 16384 and 1 <= h <= 16384):
        raise ValueError(f"Invalid Lyonir final crop {w}x{h}")
    tagged = dict(latent)
    tagged[CROP_KEY] = {"width": w, "height": h, "anchor": str(anchor)}
    return tagged


def crop_decoder_result(result, samples):
    """Post-crop the built-in VAE decoded IMAGE only for Lyonir-tagged LATENT."""
    if not isinstance(samples, dict):
        return result
    crop = samples.get(CROP_KEY)
    if not isinstance(crop, dict):
        return result
    if not isinstance(result, (list, tuple)) or not result:
        return result
    from .lyonir_sampler import _crop_images
    image = result[0]
    # The same strict hard-crop helper used by Lyonir Sampler's IMAGE output.
    # It refuses any undersized image rather than quietly exporting 704 px.
    image = _crop_images(image, int(crop["width"]), int(crop["height"]), crop.get("anchor", "center"))
    if isinstance(result, tuple):
        return (image, *result[1:])
    return [image, *result[1:]]


def _patch_decoder(cls):
    original = getattr(cls, "decode", None)
    if not callable(original):
        return False
    if getattr(original, "_lyonir_pixel_crop_hook", False):
        return True

    @wraps(original)
    def lyonir_decode(self, vae, samples, *args, **kwargs):
        decoded = original(self, vae, samples, *args, **kwargs)
        return crop_decoder_result(decoded, samples)

    lyonir_decode._lyonir_pixel_crop_hook = True
    cls.decode = lyonir_decode
    return True


def install_native_vae_crop_hooks():
    """Install once, after the base ComfyUI nodes module has been imported."""
    try:
        import nodes
    except ImportError:
        _LOG.warning("ComfyUI builtin VAE decoders unavailable; LATENT exact crop hooks not installed")
        return False
    registry = getattr(nodes, "NODE_CLASS_MAPPINGS", {})
    success = []
    for name in ("VAEDecode", "VAEDecodeTiled"):
        # Patch the public class and any separately registered implementation.
        # ComfyUI versions may install an alias/adapter into the node mapping.
        targets = [getattr(nodes, name, None)]
        if isinstance(registry, dict):
            targets.append(registry.get(name))
        for cls in targets:
            if cls is not None and _patch_decoder(cls):
                if name not in success:
                    success.append(name)
    _LOG.info("Lyonir exact crop enabled for native VAE decoders: %s", ", ".join(success) or "none")
    if success:
        print(f"[Lyonir Studio] LATENT exact crop active: {', '.join(success)}")
    else:
        _LOG.warning("Lyonir LATENT crop could not patch stock VAE decoders; native LATENT outputs will decode at native resolution")
    return bool(success)
