from __future__ import annotations

from typing import Tuple, Dict
import numpy as np
import torch
import torch.nn.functional as F


OUTPUT_CLEANUP_MODES = [
    "Clean Voice (recommended)",
    "Strong Clean",
    "Off",
]


def _as_float_mono(wav) -> np.ndarray:
    x = np.asarray(wav, dtype=np.float32)

    if x.ndim == 0:
        x = x.reshape(1)
    elif x.ndim > 1:
        if x.shape[0] <= 8:
            x = np.mean(x, axis=0)
        else:
            x = x.reshape(-1)

    x = np.nan_to_num(x.reshape(-1), nan=0.0, posinf=0.0, neginf=0.0)
    return np.ascontiguousarray(x, dtype=np.float32)


def _spectral_denoise(
    wav: np.ndarray,
    sr: int,
    *,
    strong: bool,
) -> Tuple[np.ndarray, float]:
    """
    Conservative post-synthesis cleanup.

    Noise is estimated from the lowest-energy STFT frames. The cleaner only
    becomes aggressive when those frames are clearly quieter than normal speech,
    which protects timbre on clips without true pauses.
    """
    if wav.size < 64:
        return wav, 0.0

    original_len = int(wav.size)
    wav = wav - np.float32(np.mean(wav, dtype=np.float64))

    n_fft = 1024 if sr >= 16000 else 512
    n_fft = min(
        n_fft,
        max(64, 2 ** int(np.floor(np.log2(max(wav.size, 64))))),
    )
    hop = max(16, n_fft // 4)
    window = torch.hann_window(n_fft, dtype=torch.float32)
    x = torch.from_numpy(np.ascontiguousarray(wav)).float()

    with torch.inference_mode():
        spec = torch.stft(
            x,
            n_fft=n_fft,
            hop_length=hop,
            win_length=n_fft,
            window=window,
            center=True,
            return_complex=True,
        )
        mag = spec.abs()
        power = mag.square()

        frame_energy = torch.mean(power, dim=0)
        q = torch.quantile(frame_energy, 0.15 if not strong else 0.22)
        quiet_idx = frame_energy <= q

        median_energy = torch.median(frame_energy)
        if bool(quiet_idx.any()):
            quiet_median = torch.median(frame_energy[quiet_idx])
            noise_mag = torch.median(mag[:, quiet_idx], dim=1).values[:, None]
        else:
            quiet_median = median_energy
            noise_mag = torch.zeros((mag.shape[0], 1), dtype=mag.dtype)

        quiet_ratio = float(quiet_median / (median_energy + 1e-12))

        # If the "quiet" frames are not actually much quieter than speech,
        # use little/no spectral gating to avoid thinning the voice.
        confidence = max(0.0, min(1.0, (0.55 - quiet_ratio) / 0.45))

        alpha = (0.90 if not strong else 1.40) * confidence
        noise_power = noise_mag.square()

        wiener = power / (power + alpha * noise_power + 1e-12)
        floor = 0.45 if not strong else 0.25
        gain = floor + (1.0 - floor) * wiener
        gain = 1.0 - confidence * (1.0 - gain)

        # Smooth the mask to prevent musical-noise artifacts.
        m = gain.unsqueeze(0).unsqueeze(0)
        m = F.avg_pool2d(
            F.pad(m, (1, 1, 1, 1), mode="replicate"),
            kernel_size=3,
            stride=1,
        )
        gain = m.squeeze(0).squeeze(0)

        # Remove rumble/DC gently.
        freqs = torch.linspace(0.0, float(sr) / 2.0, spec.shape[0])
        band = torch.ones_like(freqs)

        low0, low1 = ((35.0, 65.0) if not strong else (45.0, 80.0))
        low_floor = 0.15 if not strong else 0.08

        band[freqs <= low0] = low_floor
        low_transition = (freqs > low0) & (freqs < low1)
        if bool(low_transition.any()):
            band[low_transition] = low_floor + (
                (freqs[low_transition] - low0) / max(low1 - low0, 1.0)
            ) * (1.0 - low_floor)

        # A gentle top-end rolloff removes a lot of synthetic hiss while keeping
        # normal speech detail. At 24 kHz this mainly affects the extreme top end.
        hi0, hi1 = ((9500.0, 11500.0) if not strong else (8500.0, 10500.0))
        hi_floor = 0.15 if not strong else 0.07

        if (float(sr) / 2.0) > hi0:
            band[freqs >= hi1] = hi_floor
            high_transition = (freqs > hi0) & (freqs < hi1)
            if bool(high_transition.any()):
                band[high_transition] = 1.0 - (
                    (freqs[high_transition] - hi0) / max(hi1 - hi0, 1.0)
                ) * (1.0 - hi_floor)

        clean_spec = spec * gain * band[:, None]

        out = torch.istft(
            clean_spec,
            n_fft=n_fft,
            hop_length=hop,
            win_length=n_fft,
            window=window,
            center=True,
            length=original_len,
        )

    y = out.cpu().numpy().astype(np.float32, copy=False)

    # Remove tiny edge clicks without touching internal pauses.
    fade = min(int(round(sr * 0.006)), y.size // 2)
    if fade > 1:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        y[:fade] *= ramp
        y[-fade:] *= ramp[::-1]

    # Peak normalization only — no compression, so vocal dynamics stay intact.
    peak = float(np.max(np.abs(y), initial=0.0))
    if peak > 1e-7:
        target_peak = 0.94
        if peak > target_peak or peak < 0.55:
            y = np.asarray(y * (target_peak / peak), dtype=np.float32)

    return np.ascontiguousarray(y, dtype=np.float32), confidence


def clean_generated_audio(
    wav,
    sr: int,
    mode: str = "Clean Voice (recommended)",
) -> Tuple[np.ndarray, Dict[str, float]]:
    x = _as_float_mono(wav)
    mode = str(mode or "Clean Voice (recommended)")

    before_rms = (
        float(np.sqrt(np.mean(np.square(x), dtype=np.float64)))
        if x.size else 0.0
    )
    before_peak = float(np.max(np.abs(x), initial=0.0))

    if mode == "Off":
        y = x
        confidence = 0.0
    else:
        y, confidence = _spectral_denoise(
            x,
            int(sr),
            strong=(mode == "Strong Clean"),
        )

    after_rms = (
        float(np.sqrt(np.mean(np.square(y), dtype=np.float64)))
        if y.size else 0.0
    )
    after_peak = float(np.max(np.abs(y), initial=0.0))

    return y, {
        "before_rms": before_rms,
        "after_rms": after_rms,
        "before_peak": before_peak,
        "after_peak": after_peak,
        "noise_confidence": float(confidence),
    }
