from __future__ import annotations

"""
High-fidelity zero-shot voice-clone helpers for Qwen3-TTS Base.

The goal of this module is to maximize speaker similarity without changing
Transformers globally or modifying the upstream Qwen model weights.

Key choices:
- ICL prompt path (ref audio + exact transcript) whenever x_vector_only=False.
- 1.7B Base is recommended by the UI for maximum fidelity.
- Reference cleanup is deliberately conservative: mono, DC removal, edge-silence
  trim, and peak normalization. No denoising/EQ is applied because those can
  alter the very timbre we are trying to clone.
- Optional multi-candidate generation. Candidates are ranked with Qwen's own
  speaker encoder and the closest one to the reference embedding is returned.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence, Tuple
import math
import numpy as np
import torch
import torch.nn.functional as F


CLONE_PROFILES = [
    "Maximum Similarity",
    "Balanced",
    "Official Defaults",
    "Custom",
]

REFERENCE_PROCESSING = [
    "HQ Clean (recommended)",
    "Original",
]


def _emit_progress(progress_callback, fraction: float, stage: str = "") -> None:
    """Best-effort progress hook used by ComfyUI nodes without coupling this module to ComfyUI."""
    if progress_callback is None:
        return
    try:
        progress_callback(max(0.0, min(1.0, float(fraction))), str(stage))
    except Exception:
        # Progress UI must never break audio generation.
        pass


@dataclass
class CloneResult:
    wavs: List[np.ndarray]
    sample_rate: int
    similarity: float | None
    candidate_similarities: List[float | None]
    performance_similarity: float | None
    candidate_performance_similarities: List[float | None]
    selection_score: float | None
    effective_temperature: float


def _seed_everything(seed: int) -> None:
    seed = int(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        try:
            torch.xpu.manual_seed_all(seed)
        except Exception:
            pass
    np.random.seed(seed % (2**32))


def _as_mono_float32(audio_tuple: Tuple[np.ndarray, int]) -> Tuple[np.ndarray, int]:
    wav, sr = audio_tuple
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim == 2:
        # Handle both [channels, samples] and [samples, channels].
        if arr.shape[0] <= 8:
            arr = arr.mean(axis=0)
        elif arr.shape[1] <= 8:
            arr = arr.mean(axis=1)
        else:
            arr = arr.reshape(-1)
    elif arr.ndim > 2:
        arr = arr.reshape(-1)
    arr = np.ascontiguousarray(arr.reshape(-1), dtype=np.float32)
    if not np.isfinite(arr).all():
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return arr, int(sr)


def _trim_edge_silence(
    wav: np.ndarray,
    sr: int,
    threshold_db_below_peak: float = 45.0,
    pad_seconds: float = 0.15,
) -> np.ndarray:
    if wav.size < max(32, int(sr * 0.05)):
        return wav

    frame = max(1, int(sr * 0.020))
    hop = max(1, int(sr * 0.010))
    if wav.size < frame:
        return wav

    # Fast frame RMS without external audio dependencies.
    sq = np.square(wav.astype(np.float64, copy=False))
    csum = np.concatenate(([0.0], np.cumsum(sq)))
    starts = np.arange(0, wav.size - frame + 1, hop, dtype=np.int64)
    ends = starts + frame
    rms = np.sqrt(np.maximum((csum[ends] - csum[starts]) / frame, 0.0))
    peak_rms = float(rms.max(initial=0.0))
    if peak_rms <= 1e-8:
        return wav

    threshold = peak_rms * (10.0 ** (-float(threshold_db_below_peak) / 20.0))
    active = np.flatnonzero(rms >= threshold)
    if active.size == 0:
        return wav

    pad = int(max(0.0, pad_seconds) * sr)
    start = max(0, int(starts[int(active[0])]) - pad)
    end_frame = int(starts[int(active[-1])]) + frame
    end = min(wav.size, end_frame + pad)
    if end <= start:
        return wav
    return np.ascontiguousarray(wav[start:end], dtype=np.float32)


def prepare_reference_audio(
    audio_tuple: Tuple[np.ndarray, int],
    mode: str = "HQ Clean (recommended)",
) -> Tuple[np.ndarray, int, Dict[str, float]]:
    wav, sr = _as_mono_float32(audio_tuple)
    before_seconds = float(wav.size / max(sr, 1))

    if mode == "HQ Clean (recommended)":
        # DC offset can bias low-frequency statistics while carrying no useful
        # identity information.
        if wav.size:
            wav = wav - np.float32(np.mean(wav, dtype=np.float64))
        wav = _trim_edge_silence(wav, sr)

        # Normalize only gain, never dynamics/EQ/noise. This preserves timbre.
        peak = float(np.max(np.abs(wav), initial=0.0))
        if peak > 1e-5:
            target_peak = 0.95
            wav = np.asarray(wav * (target_peak / peak), dtype=np.float32)

    after_seconds = float(wav.size / max(sr, 1))
    meta = {
        "duration_before": before_seconds,
        "duration_after": after_seconds,
        "sample_rate": float(sr),
    }
    return np.ascontiguousarray(wav, dtype=np.float32), sr, meta


def _resample_linear(wav: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if int(orig_sr) == int(target_sr) or wav.size == 0:
        return np.asarray(wav, dtype=np.float32)
    new_len = max(1, int(round(wav.size * float(target_sr) / float(orig_sr))))
    t = torch.from_numpy(np.ascontiguousarray(wav, dtype=np.float32)).view(1, 1, -1)
    with torch.no_grad():
        out = F.interpolate(t, size=new_len, mode="linear", align_corners=False)
    return out.view(-1).cpu().numpy().astype(np.float32, copy=False)


def _flatten_embedding(x: Any) -> torch.Tensor:
    if isinstance(x, torch.Tensor):
        t = x.detach().float().cpu()
    else:
        t = torch.as_tensor(x, dtype=torch.float32).cpu()
    return t.reshape(-1)


def cosine_similarity(a: Any, b: Any) -> float:
    ta = _flatten_embedding(a)
    tb = _flatten_embedding(b)
    if ta.numel() != tb.numel() or ta.numel() == 0:
        raise ValueError(f"Speaker embedding shape mismatch: {tuple(ta.shape)} vs {tuple(tb.shape)}")
    denom = float(torch.linalg.vector_norm(ta) * torch.linalg.vector_norm(tb))
    if denom <= 1e-12:
        return float("-inf")
    return float(torch.dot(ta, tb) / denom)




def _rms_envelope(wav: np.ndarray, sr: int) -> np.ndarray:
    """Return a compact log-RMS envelope for prosody/performance comparison."""
    x = np.asarray(wav, dtype=np.float32).reshape(-1)
    if x.size == 0 or sr <= 0:
        return np.zeros(1, dtype=np.float32)
    frame = max(16, int(round(sr * 0.025)))
    hop = max(8, int(round(sr * 0.010)))
    if x.size < frame:
        rms = np.array([float(np.sqrt(np.mean(np.square(x), dtype=np.float64) + 1e-12))], dtype=np.float32)
    else:
        sq = np.square(x.astype(np.float64, copy=False))
        csum = np.concatenate(([0.0], np.cumsum(sq)))
        starts = np.arange(0, x.size - frame + 1, hop, dtype=np.int64)
        ends = starts + frame
        rms = np.sqrt(np.maximum((csum[ends] - csum[starts]) / frame, 1e-12)).astype(np.float32)
    return np.log1p(rms * 100.0).astype(np.float32, copy=False)


def _resample_feature_curve(values: np.ndarray, points: int = 128) -> np.ndarray:
    v = np.asarray(values, dtype=np.float32).reshape(-1)
    if v.size == 0:
        return np.zeros(points, dtype=np.float32)
    if v.size == 1:
        return np.full(points, float(v[0]), dtype=np.float32)
    old_x = np.linspace(0.0, 1.0, num=v.size, dtype=np.float64)
    new_x = np.linspace(0.0, 1.0, num=points, dtype=np.float64)
    return np.interp(new_x, old_x, v).astype(np.float32)


def performance_similarity(
    candidate_wav: np.ndarray,
    candidate_sr: int,
    guide_wav: np.ndarray,
    guide_sr: int,
) -> float:
    """
    Lightweight same-text delivery similarity in [0, 1].

    The guide and candidate should speak the same target text. The score rewards:
    - similar total duration (a strong proxy for speaking rate);
    - similar pause/emphasis timing via a normalized RMS envelope;
    - similar envelope dynamics.

    This intentionally avoids ASR/pitch dependencies so the clone pack stays
    self-contained and does not add heavyweight models or licenses.
    """
    cand = np.asarray(candidate_wav, dtype=np.float32).reshape(-1)
    guide = np.asarray(guide_wav, dtype=np.float32).reshape(-1)
    if cand.size == 0 or guide.size == 0 or candidate_sr <= 0 or guide_sr <= 0:
        return 0.0

    cand_dur = cand.size / float(candidate_sr)
    guide_dur = guide.size / float(guide_sr)
    if cand_dur <= 0.0 or guide_dur <= 0.0:
        return 0.0

    # Same text should have similar duration when pace is followed. The log ratio
    # treats faster/slower deviations symmetrically.
    duration_delta = abs(math.log(max(cand_dur, 1e-6) / max(guide_dur, 1e-6)))
    duration_score = math.exp(-duration_delta / 0.28)

    cand_env = _resample_feature_curve(_rms_envelope(cand, int(candidate_sr)))
    guide_env = _resample_feature_curve(_rms_envelope(guide, int(guide_sr)))

    cand_std = float(np.std(cand_env))
    guide_std = float(np.std(guide_env))
    if cand_std > 1e-6 and guide_std > 1e-6:
        c = (cand_env - float(np.mean(cand_env))) / cand_std
        g = (guide_env - float(np.mean(guide_env))) / guide_std
        corr = float(np.dot(c, g) / max(float(np.linalg.norm(c) * np.linalg.norm(g)), 1e-9))
        envelope_score = max(0.0, min(1.0, 0.5 * (corr + 1.0)))
    else:
        envelope_score = 0.5

    dynamics_score = math.exp(-abs(cand_std - guide_std) / 0.45)
    score = 0.58 * duration_score + 0.32 * envelope_score + 0.10 * dynamics_score
    return max(0.0, min(1.0, float(score)))


def _extract_candidate_embedding(model: Any, wav: np.ndarray, sr: int) -> Any:
    # Official Qwen wrapper stores Qwen3TTSForConditionalGeneration in .model.
    core = getattr(model, "model", None)
    if core is None or not hasattr(core, "extract_speaker_embedding"):
        raise RuntimeError("This Qwen3-TTS backend does not expose speaker embedding extraction.")

    target_sr = int(getattr(core, "speaker_encoder_sample_rate", 24000))
    emb_wav = _resample_linear(np.asarray(wav, dtype=np.float32), int(sr), target_sr)
    with torch.inference_mode():
        return core.extract_speaker_embedding(audio=emb_wav, sr=target_sr)


def _profile_temperature(profile: str, custom_temperature: float) -> float:
    # 0.65 is intentionally conservative: lower temperatures can improve
    # consistency but very low values can cause early-EOS collapse.
    if profile == "Maximum Similarity":
        return 0.65
    if profile == "Balanced":
        return 0.78
    if profile == "Official Defaults":
        return 0.90
    return float(custom_temperature)


def _warn_reference(meta: Dict[str, float]) -> None:
    duration = float(meta.get("duration_after", 0.0))
    sr = int(meta.get("sample_rate", 0.0))
    if duration < 5.0:
        print(
            f"[Lyonir Qwen3-TTS] Voice Clone HQ warning: reference is only {duration:.1f}s. "
            "For stronger identity, use a clean ~10-15s single-speaker clip."
        )
    elif duration > 30.0:
        print(
            f"[Lyonir Qwen3-TTS] Voice Clone HQ note: reference is {duration:.1f}s. "
            "A clean, focused 10-20s excerpt can be easier for ICL cloning."
        )
    if sr != 24000:
        print(
            f"[Lyonir Qwen3-TTS] Voice Clone HQ: reference is {sr} Hz. "
            "Qwen will resample for its speaker encoder; a native 24 kHz source is ideal."
        )


def generate_hq_voice_clone(
    *,
    model: Any,
    ref_audio_tuple: Tuple[np.ndarray, int],
    ref_text: str,
    target_text: str,
    language: str,
    accent_anchor_audio_tuple: Tuple[np.ndarray, int] | None = None,
    accent_anchor_text: str | None = None,
    alternate_anchor_audio_tuple: Tuple[np.ndarray, int] | None = None,
    alternate_anchor_text: str | None = None,
    seed: int,
    max_new_tokens: int,
    top_p: float,
    top_k: int,
    temperature: float,
    repetition_penalty: float,
    x_vector_only: bool,
    clone_profile: str,
    candidate_count: int,
    reference_processing: str,
    subtalker_temperature: float | None = None,
    performance_guide_audio_tuple: Tuple[np.ndarray, int] | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> CloneResult:
    if not str(target_text).strip():
        raise RuntimeError("Target text is required.")
    if (
        not x_vector_only
        and accent_anchor_audio_tuple is None
        and not str(ref_text).strip()
    ):
        raise RuntimeError(
            "Maximum voice fidelity requires the exact reference transcript. "
            "Provide ref_text, or use a valid accent/emotion anchor."
        )

    _emit_progress(progress_callback, 0.03, "Preparing reference audio")
    ref_wav, ref_sr, meta = prepare_reference_audio(ref_audio_tuple, reference_processing)
    _warn_reference(meta)
    _emit_progress(progress_callback, 0.10, "Encoding speaker identity")

    # When an external/native accent or emotion anchor is active, the real
    # reference audio is used for IDENTITY ONLY. This prevents the calm cadence
    # of the source recording from leaking back into the final performance.
    identity_only = bool(x_vector_only or accent_anchor_audio_tuple is not None)
    identity_prompt_items = model.create_voice_clone_prompt(
        ref_audio=(ref_wav, ref_sr),
        ref_text=None if identity_only else (str(ref_text).strip() or None),
        x_vector_only_mode=identity_only,
    )
    if not identity_prompt_items:
        raise RuntimeError("Qwen3-TTS returned an empty voice clone prompt.")
    _emit_progress(progress_callback, 0.16, "Speaker identity ready")

    ref_embedding = getattr(identity_prompt_items[0], "ref_spk_embedding", None)
    prompt_items = identity_prompt_items
    prompt_variants: List[Tuple[str, Any]] = [("reference", prompt_items)]

    def _hybrid_prompt_from_anchor(audio_tuple, text_value, label):
        anchor_wav, anchor_sr = _as_mono_float32(audio_tuple)
        anchor_text_value = str(text_value or ref_text or "").strip()
        if not anchor_text_value:
            raise RuntimeError("Accent/emotion anchor audio requires its exact transcript.")
        anchor_prompt_items = model.create_voice_clone_prompt(
            ref_audio=(anchor_wav, anchor_sr),
            ref_text=anchor_text_value,
            x_vector_only_mode=False,
        )
        if not anchor_prompt_items:
            return None
        hybrid = anchor_prompt_items[0]
        hybrid.ref_spk_embedding = identity_prompt_items[0].ref_spk_embedding
        hybrid.ref_text = anchor_text_value
        hybrid.x_vector_only_mode = False
        hybrid.icl_mode = True
        print(
            f"[Lyonir Qwen3-TTS] Hybrid prompt '{label}' active: "
            "guide codec/prosody + original speaker identity."
        )
        return [hybrid]

    if accent_anchor_audio_tuple is not None and not x_vector_only:
        primary = _hybrid_prompt_from_anchor(
            accent_anchor_audio_tuple, accent_anchor_text, "native/accent"
        )
        if primary is not None:
            prompt_items = primary
            prompt_variants = [("native/accent", primary)]

    # Instruction-First can add a second VoiceDesign prompt variant. Candidate
    # generation alternates between the native/accent guide and the stronger
    # instruction guide, while every variant keeps the REAL speaker embedding.
    if alternate_anchor_audio_tuple is not None and not x_vector_only:
        alternate = _hybrid_prompt_from_anchor(
            alternate_anchor_audio_tuple, alternate_anchor_text, "instruction"
        )
        if alternate is not None:
            prompt_variants.append(("instruction", alternate))
    _emit_progress(progress_callback, 0.22, "Conditioning ready")
    effective_temperature = _profile_temperature(clone_profile, temperature)
    if subtalker_temperature is None:
        effective_subtalker_temperature = effective_temperature
    elif clone_profile == "Custom":
        effective_subtalker_temperature = float(subtalker_temperature)
    else:
        effective_subtalker_temperature = effective_temperature

    # Keep top_p at 1 for similarity profiles; aggressive nucleus truncation at
    # lower temperatures can destabilize speech termination.
    effective_top_p = 1.0 if clone_profile in ("Maximum Similarity", "Balanced") else float(top_p)
    count = max(1, min(int(candidate_count), 6))

    guide_wav: np.ndarray | None = None
    guide_sr: int | None = None
    if performance_guide_audio_tuple is not None:
        guide_wav, guide_sr = _as_mono_float32(performance_guide_audio_tuple)

    candidates: List[np.ndarray] = []
    candidate_variants: List[str] = []
    similarities: List[float | None] = []
    performance_similarities: List[float | None] = []
    output_sr: int | None = None

    for i in range(count):
        # Most of the runtime is spent generating candidates. Move the ComfyUI
        # progress bar across this region so users get continuous visual feedback.
        start_frac = 0.24 + (0.66 * i / max(count, 1))
        _emit_progress(progress_callback, start_frac, f"Generating candidate {i+1}/{count}")

        candidate_seed = (int(seed) + i * 1009) & 0xFFFFFFFFFFFFFFFF
        _seed_everything(candidate_seed)

        variant_label, variant_prompt = prompt_variants[i % len(prompt_variants)]
        wavs, sr = model.generate_voice_clone(
            text=str(target_text),
            language=str(language),
            voice_clone_prompt=variant_prompt,
            max_new_tokens=int(max_new_tokens),
            do_sample=True,
            top_p=float(effective_top_p),
            top_k=int(top_k),
            temperature=float(effective_temperature),
            repetition_penalty=float(repetition_penalty),
            subtalker_dosample=True,
            subtalker_top_p=float(effective_top_p),
            subtalker_top_k=int(top_k),
            subtalker_temperature=float(effective_subtalker_temperature),
        )
        if not wavs:
            continue
        wav = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        candidates.append(wav)
        candidate_variants.append(variant_label)
        output_sr = int(sr)

        score: float | None = None
        if ref_embedding is not None:
            try:
                cand_emb = _extract_candidate_embedding(model, wav, int(sr))
                score = cosine_similarity(ref_embedding, cand_emb)
            except Exception as exc:
                print(f"[Lyonir Qwen3-TTS] Candidate speaker similarity unavailable: {exc}")
        similarities.append(score)

        perf_score: float | None = None
        if guide_wav is not None and guide_sr is not None:
            try:
                perf_score = performance_similarity(wav, int(sr), guide_wav, int(guide_sr))
            except Exception as exc:
                print(f"[Lyonir Qwen3-TTS] Candidate performance similarity unavailable: {exc}")
        performance_similarities.append(perf_score)

        done_frac = 0.24 + (0.66 * (i + 1) / max(count, 1))
        _emit_progress(progress_callback, done_frac, f"Candidate {i+1}/{count} ready")
        if score is None:
            print(f"[Lyonir Qwen3-TTS] Voice Clone HQ candidate {i+1}/{count} generated.")
        else:
            perf_text = "" if perf_score is None else f", performance={perf_score:.5f}"
            print(
                f"[Lyonir Qwen3-TTS] Voice Clone HQ candidate {i+1}/{count} "
                f"[{variant_label}]: speaker cosine={score:.5f}{perf_text}"
            )

    if not candidates or output_sr is None:
        raise RuntimeError("Voice Clone HQ generation returned no audio candidates.")

    _emit_progress(progress_callback, 0.93, "Selecting best identity/performance match")
    valid = [(idx, score) for idx, score in enumerate(similarities) if score is not None and math.isfinite(float(score))]
    best_selection_score: float | None = None
    selected_perf: float | None = None

    if valid:
        identity_best_idx, identity_best_score = max(valid, key=lambda item: float(item[1]))

        if guide_wav is None:
            best_idx, best_score = identity_best_idx, identity_best_score
            best_selection_score = float(best_score)
        else:
            # Instruction-First policy: performance matters strongly, but only among
            # candidates that remain very close to the best speaker-identity match.
            # This avoids trading a convincing clone for a completely different voice.
            identity_floor = float(identity_best_score) - 0.050
            identity_weight = 0.55
            performance_weight = 0.45
            ranked = []
            for idx, identity_score in valid:
                if float(identity_score) < identity_floor:
                    continue
                perf = performance_similarities[idx] if idx < len(performance_similarities) else None
                if perf is None or not math.isfinite(float(perf)):
                    perf = 0.0
                combined = identity_weight * float(identity_score) + performance_weight * float(perf)
                ranked.append((idx, float(identity_score), float(perf), float(combined)))

            if ranked:
                best_idx, best_score, selected_perf, best_selection_score = max(
                    ranked, key=lambda item: item[3]
                )
            else:
                best_idx, best_score = identity_best_idx, identity_best_score
                best_selection_score = float(best_score)

        if selected_perf is None and best_idx < len(performance_similarities):
            selected_perf = performance_similarities[best_idx]

        extra = ""
        if selected_perf is not None:
            extra = f", performance={float(selected_perf):.5f}"
        variant = candidate_variants[best_idx] if best_idx < len(candidate_variants) else "unknown"
        print(
            f"[Lyonir Qwen3-TTS] Voice Clone HQ selected candidate {best_idx+1}/{len(candidates)} "
            f"[{variant}] with speaker cosine={float(best_score):.5f}{extra}."
        )
    else:
        best_score = None
        perf_valid = [
            (idx, score)
            for idx, score in enumerate(performance_similarities)
            if score is not None and math.isfinite(float(score))
        ]
        if perf_valid and guide_wav is not None:
            best_idx, selected_perf = max(perf_valid, key=lambda item: float(item[1]))
            best_selection_score = float(selected_perf)
            print(
                f"[Lyonir Qwen3-TTS] Identity ranking unavailable; selected candidate "
                f"{best_idx+1}/{len(candidates)} by performance={float(selected_perf):.5f}."
            )
        else:
            best_idx = 0
            selected_perf = performance_similarities[0] if performance_similarities else None
            if selected_perf is not None:
                best_selection_score = float(selected_perf)
            if len(candidates) > 1:
                print("[Lyonir Qwen3-TTS] Identity ranking unavailable; returning candidate 1.")

    _emit_progress(progress_callback, 1.0, "Voice clone ready")
    return CloneResult(
        wavs=[candidates[best_idx]],
        sample_rate=output_sr,
        similarity=None if best_score is None else float(best_score),
        candidate_similarities=similarities,
        performance_similarity=None if selected_perf is None else float(selected_perf),
        candidate_performance_similarities=performance_similarities,
        selection_score=None if best_selection_score is None else float(best_selection_score),
        effective_temperature=float(effective_temperature),
    )
