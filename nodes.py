from __future__ import annotations

from typing import Dict, Any
import numpy as np
import torch

try:
    from comfy.utils import ProgressBar
except Exception:
    ProgressBar = None

from .backend import (
    load_model,
    load_ptbr_model,
    unload_all,
    ensure_backend,
    PTBR_SPEAKER,
    PTBR_LANGUAGE,
)
from .clone_hq import (
    generate_hq_voice_clone,
    prepare_reference_audio,
    CLONE_PROFILES,
    REFERENCE_PROCESSING,
)
from .audio_clean import clean_generated_audio, OUTPUT_CLEANUP_MODES


LANGUAGES = [
    "Auto",
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "German",
    "French",
    "Russian",
    "Portuguese",
    "Portuguese (Brazil)",
    "Spanish",
    "Italian",
]

LANGUAGE_MAP = {
    "Auto": "auto",
    "Chinese": "chinese",
    "English": "english",
    "Japanese": "japanese",
    "Korean": "korean",
    "German": "german",
    "French": "french",
    "Russian": "russian",
    "Portuguese": "portuguese",
    "Portuguese (Brazil)": "portuguese",
    "Spanish": "spanish",
    "Italian": "italian",
}

BRAZILIAN_INSTRUCT = (
    "Speak as a native Brazilian Portuguese speaker, with authentic Brazilian "
    "pronunciation, rhythm, vowel quality, consonants, intonation and prosody. "
    "Do not use European Portuguese pronunciation or prosody."
)

STRICT_BRAZILIAN_INSTRUCT = (
    "Speak only in native Brazilian Portuguese (pt-BR). Use unmistakably Brazilian "
    "pronunciation, vowel openness, consonant realization, rhythm, stress, connected "
    "speech and intonation. Never use European Portuguese (pt-PT) phonetics, rhythm, "
    "reduced vowels or prosody. Prefer a fluent contemporary Brazilian delivery and avoid pt-PT reduced-vowel patterns."
)

IDENTITY_REFERENCE_TEXT_EN = (
    "This is a clean reference recording of the speaker's natural voice. "
    "The delivery is steady, clear, relaxed, and easy to understand."
)

IDENTITY_REFERENCE_TEXT_PTBR = (
    "Olá. Esta é uma gravação de referência da minha voz natural. "
    "Eu falo de forma clara, fluida e confiante, com boa articulação e "
    "um ritmo brasileiro conversacional, vivo e natural."
)

DEVICES = ["auto", "cuda", "cpu", "mps", "xpu"]
PRECISIONS = ["bf16", "fp16", "fp32"]
ATTENTION = ["auto", "sage_attention", "sdpa", "eager", "flash_attention_2"]
PTBR_ENGINES = [
    "Native PT-BR Hybrid (recommended)",
    "Native PT-BR Natural",
    "Native PT-BR Maximum Identity",
    "Native PT-BR Custom (advanced)",
]

BRAZILIAN_CLONE_MODES = [
    "Native PT-BR Hybrid (recommended)",
    "Native PT-BR Natural",
    "Native PT-BR Maximum Identity",
    "Native PT-BR Custom (advanced)",
]

OFFICIAL_CLONE_MODES = [
    "Official Qwen ICL Clone (recommended)",
    "Official Qwen Speaker-Only",
]
SPEAKERS = [
    "Leonardo",
    "Aiden",
    "Dylan",
    "Eric",
    "Ono_Anna",
    "Ryan",
    "Serena",
    "Sohee",
    "Uncle_Fu",
    "Vivian",
]


# Leonardo is a deliberately MALE Brazilian preset.
#
# We do not expose the public PT-BR checkpoint's pb_sotaque speaker directly as
# "Leonardo", because that checkpoint's single voice may not match the desired
# male identity. Instead, Leonardo is built as a hybrid:
#   1) Aiden (official Qwen male speaker) supplies the masculine speaker identity.
#   2) The dedicated PT-BR checkpoint supplies Brazilian pronunciation/prosody.
#   3) Qwen Base 1.7B combines the male speaker embedding with the PT-BR codec
#      reference and ranks multiple candidates by similarity to the male anchor.
LEONARDO_IDENTITY_SPEAKER = "aiden"
LEONARDO_ANCHOR_TEXT = (
    "Olá, eu sou Leonardo. Esta é uma voz masculina brasileira, natural, clara, "
    "segura e confortável de ouvir."
)
LEONARDO_MALE_INSTRUCT = (
    "Use an unmistakably adult male voice with a natural masculine timbre, "
    "medium-to-low pitch, clear midrange and confident relaxed delivery. "
    "The speaker must remain male; do not feminize the voice. "
    "Speak with native Brazilian Portuguese pronunciation and Brazilian prosody."
)


def _qwen_language(language: str) -> str:
    return LANGUAGE_MAP.get(str(language), str(language).lower())


def _with_brazilian_instruction(language: str, instruct: str) -> str:
    user = str(instruct or "").strip()
    if str(language) != "Portuguese (Brazil)":
        return user
    if not user:
        return BRAZILIAN_INSTRUCT
    return f"{BRAZILIAN_INSTRUCT} {user}"


def _generate_ptbr_anchor_audio(
    *,
    ref_text: str,
    checkpoint_step: str,
    device: str,
    precision: str,
    attention: str,
    download_if_missing: bool,
    seed: int,
    style_instruct: str = "",
):
    """Generate a native-Brazilian pronunciation/prosody anchor for hybrid cloning."""
    if not str(ref_text).strip():
        raise RuntimeError("Native PT-BR Hybrid requires the exact ref_text transcript.")

    model = load_ptbr_model(
        checkpoint_step=str(checkpoint_step),
        device=device,
        precision=precision,
        attention=attention,
        download_if_missing=bool(download_if_missing),
        custom_model_path="",
    )
    _seed_everything((int(seed) + 7919) & 0xFFFFFFFFFFFFFFFF)
    try:
        wavs, sr = model.generate_custom_voice(
            text=str(ref_text).strip(),
            speaker=PTBR_SPEAKER,
            language=PTBR_LANGUAGE,
            instruct=(
                "Speak naturally as a native Brazilian Portuguese speaker, with Brazilian pronunciation, "
                "Brazilian rhythm and Brazilian prosody. Avoid European Portuguese pronunciation and prosody. "
                + (
                    "Follow the user's performance instruction as strongly and clearly as possible. "
                    "Prioritize the requested speaking rate, emotion, energy, emphasis, pause timing, "
                    "intonation, pitch movement and intensity. Do not neutralize or soften the requested "
                    f"performance. User performance instruction: {str(style_instruct).strip()}"
                    if str(style_instruct).strip()
                    else "Use a natural conversational delivery."
                )
            ),
            max_new_tokens=2048,
            top_p=1.0,
            top_k=50,
            temperature=0.75,
            repetition_penalty=1.05,
        )
        if not wavs:
            raise RuntimeError("PT-BR anchor generation returned no audio.")
        return (np.asarray(wavs[0], dtype=np.float32).reshape(-1), int(sr))
    finally:
        # The Base model is loaded afterwards; release the PT-BR checkpoint first
        # so a 24 GB card does not have to keep both models resident.
        try:
            del model
        except Exception:
            pass
        unload_all()


def _generate_instruction_performance_guide(
    *,
    text: str,
    language: str,
    instruction: str,
    device: str,
    precision: str,
    attention: str,
    seed: int,
    max_new_tokens: int = 2048,
):
    """Generate a same-text performance guide with Qwen VoiceDesign.

    The guide's speaker identity is deliberately discarded later. Only its codec/prosody
    is used together with the real reference speaker embedding, which lets VoiceDesign
    focus on following the requested acting, pace and emotion.
    """
    if not str(text).strip():
        raise RuntimeError("Performance guide target text is empty.")
    if not str(instruction).strip():
        raise RuntimeError("Performance guide requires a Voice Instruction.")

    model = load_model("VoiceDesign", "1.7B", device, precision, attention, "")
    _seed_everything((int(seed) + 104729) & 0xFFFFFFFFFFFFFFFF)

    strong_instruction = (
        "Follow the user's requested vocal performance as strongly and literally as possible. "
        "This audio will be used only as a delivery/prosody guide, so prioritize the requested "
        "speaking rate, emotion, energy, emphasis, pause timing, intonation, pitch movement and "
        "intensity. Make the requested performance clearly audible while remaining natural, human "
        "and intelligible. Do not neutralize, soften or average the requested style. "
    )
    if str(language) == "Portuguese (Brazil)":
        strong_instruction += STRICT_BRAZILIAN_INSTRUCT + " "
    strong_instruction += f"User Voice Instruction: {str(instruction).strip()}"

    try:
        wavs, sr = model.generate_voice_design(
            text=str(text).strip(),
            instruct=strong_instruction,
            language=_qwen_language(language),
            max_new_tokens=int(max_new_tokens),
            top_p=1.0,
            top_k=50,
            temperature=0.62,
            repetition_penalty=1.05,
        )
        if not wavs:
            raise RuntimeError("VoiceDesign performance guide returned no audio.")
        return (np.asarray(wavs[0], dtype=np.float32).reshape(-1), int(sr))
    finally:
        try:
            del model
        except Exception:
            pass
        unload_all()


def _generate_leonardo_male_identity_audio(
    *,
    device: str,
    precision: str,
    attention: str,
    seed: int,
    user_instruct: str = "",
):
    """
    Create a stable male identity anchor for the Leonardo preset.

    Aiden is an official Qwen CustomVoice male speaker. We use only this
    generated clip as the identity source for Qwen's speaker encoder. Brazilian
    pronunciation itself comes from the separate PT-BR anchor.
    """
    model = load_model(
        "CustomVoice",
        "1.7B",
        device,
        precision,
        attention,
        "",
    )
    _seed_everything((int(seed) + 3571) & 0xFFFFFFFFFFFFFFFF)

    user = str(user_instruct or "").strip()
    identity_instruct = LEONARDO_MALE_INSTRUCT
    if user:
        identity_instruct = (
            f"{LEONARDO_MALE_INSTRUCT} Apply this additional style while keeping "
            f"the voice male: {user}"
        )

    try:
        wavs, sr = model.generate_custom_voice(
            text=LEONARDO_ANCHOR_TEXT,
            speaker=LEONARDO_IDENTITY_SPEAKER,
            language="portuguese",
            instruct=identity_instruct,
            max_new_tokens=2048,
            top_p=1.0,
            top_k=50,
            temperature=0.70,
            repetition_penalty=1.05,
        )
        if not wavs:
            raise RuntimeError("Leonardo male identity generation returned no audio.")
        return (np.asarray(wavs[0], dtype=np.float32).reshape(-1), int(sr))
    finally:
        try:
            del model
        except Exception:
            pass
        unload_all()


def _generate_leonardo_ptbr_anchor_audio(
    *,
    checkpoint_step: str,
    device: str,
    precision: str,
    attention: str,
    download_if_missing: bool,
    seed: int,
):
    """Generate the native-Brazilian codec/prosody anchor used by Leonardo."""
    return _generate_ptbr_anchor_audio(
        ref_text=LEONARDO_ANCHOR_TEXT,
        checkpoint_step=checkpoint_step,
        device=device,
        precision=precision,
        attention=attention,
        download_if_missing=download_if_missing,
        seed=(int(seed) + 4813) & 0xFFFFFFFFFFFFFFFF,
    )



def _generate_native_ptbr_target_audio(
    *,
    text: str,
    style_instruct: str,
    checkpoint_step: str,
    device: str,
    precision: str,
    attention: str,
    download_if_missing: bool,
    seed: int,
    max_new_tokens: int = 2048,
):
    """Generate the *final text* with the real Brazilian Qwen fine-tune."""
    if not str(text).strip():
        raise RuntimeError("PT-BR target text is empty.")

    model = load_ptbr_model(
        checkpoint_step=str(checkpoint_step),
        device=device,
        precision=precision,
        attention=attention,
        download_if_missing=bool(download_if_missing),
        custom_model_path="",
    )
    _seed_everything((int(seed) + 2089) & 0xFFFFFFFFFFFFFFFF)
    user_style = str(style_instruct or "").strip()
    instruct = STRICT_BRAZILIAN_INSTRUCT
    if user_style:
        instruct = f"{STRICT_BRAZILIAN_INSTRUCT} Preserve this requested delivery/style: {user_style}"

    try:
        wavs, sr = model.generate_custom_voice(
            text=str(text).strip(),
            speaker=PTBR_SPEAKER,
            language=PTBR_LANGUAGE,
            instruct=instruct,
            max_new_tokens=int(max_new_tokens),
            top_p=1.0,
            top_k=50,
            temperature=0.70,
            repetition_penalty=1.05,
        )
        if not wavs:
            raise RuntimeError("Native PT-BR renderer returned no audio.")
        return (np.asarray(wavs[0], dtype=np.float32).reshape(-1), int(sr))
    finally:
        try:
            del model
        except Exception:
            pass
        unload_all()


def _generate_voice_design_identity_audio(
    *,
    instruct: str,
    device: str,
    precision: str,
    attention: str,
    seed: int,
    custom_model_path: str = "",
):
    """Create only the designed speaker identity; accent is rendered separately."""
    model = load_model("VoiceDesign", "1.7B", device, precision, attention, custom_model_path)
    _seed_everything((int(seed) + 3253) & 0xFFFFFFFFFFFFFFFF)
    identity_instruct = (
        f"{str(instruct).strip()} Preserve the requested speaker identity, age, gender and timbre. "
        "For this temporary identity reference, speak Brazilian Portuguese clearly and naturally. "
        "Use a normal-to-lively Brazilian conversational pace. Do not drag syllables, vowels, or pauses. "
        "Do not sound robotic, overly careful, or slow. "
        + STRICT_BRAZILIAN_INSTRUCT
    )
    try:
        wavs, sr = model.generate_voice_design(
            text=IDENTITY_REFERENCE_TEXT_PTBR,
            instruct=identity_instruct,
            language="portuguese",
            max_new_tokens=1536,
            top_p=1.0,
            top_k=50,
            temperature=0.72,
            repetition_penalty=1.05,
        )
        if not wavs:
            raise RuntimeError("VoiceDesign identity reference returned no audio.")
        return (np.asarray(wavs[0], dtype=np.float32).reshape(-1), int(sr))
    finally:
        try:
            del model
        except Exception:
            pass
        unload_all()


def _generate_custom_identity_audio(
    *,
    speaker: str,
    model_choice: str,
    user_instruct: str,
    device: str,
    precision: str,
    attention: str,
    seed: int,
    custom_model_path: str = "",
    custom_speaker_name: str = "",
):
    """Create a clean identity-only reference from a Qwen CustomVoice speaker."""
    is_leonardo = str(speaker) == "Leonardo"
    target_speaker = LEONARDO_IDENTITY_SPEAKER if is_leonardo else (
        str(custom_speaker_name).strip()
        if str(custom_speaker_name).strip()
        else str(speaker).lower().replace(" ", "_")
    )
    identity_model_choice = "1.7B" if is_leonardo else str(model_choice)
    identity_path = "" if is_leonardo else str(custom_model_path or "")
    model = load_model(
        "CustomVoice",
        identity_model_choice,
        device,
        precision,
        attention,
        identity_path,
    )
    _seed_everything((int(seed) + 3571) & 0xFFFFFFFFFFFFFFFF)

    user = str(user_instruct or "").strip()
    if is_leonardo:
        identity_instruct = (
            "Use an unmistakably adult male voice with a natural masculine timbre, "
            "medium-to-low pitch, clear midrange and confident conversational delivery. "
            "The speaker must remain male and must not be feminized. "
            "Use a normal-to-lively Brazilian speaking pace; do not drag syllables or pauses. "
            "Speak Brazilian Portuguese naturally for this identity reference. "
            + STRICT_BRAZILIAN_INSTRUCT
        )
    else:
        identity_instruct = (
            "Preserve the selected speaker's natural identity and timbre. "
            "Speak Brazilian Portuguese naturally for this temporary identity reference. "
            "Keep a fluid normal-to-lively conversational pace; do not drag syllables or pauses. "
            "Avoid robotic or overly careful delivery. "
            + STRICT_BRAZILIAN_INSTRUCT
        )
    if user:
        identity_instruct += f" Preserve this requested voice character where it affects timbre: {user}"

    try:
        wavs, sr = model.generate_custom_voice(
            text=IDENTITY_REFERENCE_TEXT_PTBR,
            speaker=target_speaker,
            language="portuguese",
            instruct=identity_instruct,
            max_new_tokens=1536,
            top_p=1.0,
            top_k=50,
            temperature=0.72,
            repetition_penalty=1.05,
        )
        if not wavs:
            raise RuntimeError("CustomVoice identity reference returned no audio.")
        return (np.asarray(wavs[0], dtype=np.float32).reshape(-1), int(sr))
    finally:
        try:
            del model
        except Exception:
            pass
        unload_all()




def _extract_reference_speaker_embedding(
    *,
    ref_audio_tuple,
    device,
    precision,
    attention,
    reference_processing,
):
    """
    Extract speaker identity only with Qwen Base 1.7B.

    The reference codec/prosody is intentionally discarded in Expressive mode.
    """
    clean_ref, clean_ref_sr, _ = prepare_reference_audio(
        ref_audio_tuple,
        str(reference_processing),
    )

    base_model = load_model("Base", "1.7B", device, precision, attention, "")
    try:
        prompt = base_model.create_voice_clone_prompt(
            ref_audio=(clean_ref, int(clean_ref_sr)),
            ref_text=None,
            x_vector_only_mode=True,
        )
        if not prompt:
            raise RuntimeError("Qwen Base did not return a speaker embedding.")
        emb = prompt[0].ref_spk_embedding
        if isinstance(emb, torch.Tensor):
            emb = emb.detach().float().cpu()
        else:
            emb = torch.as_tensor(emb, dtype=torch.float32).detach().cpu()
        return emb.reshape(-1)
    finally:
        try:
            del base_model
        except Exception:
            pass
        unload_all()


def _render_qwen_ptbr_hybrid_from_identity(
    *,
    identity_audio,
    identity_text,
    target_text,
    voice_instruction,
    checkpoint_step,
    device,
    precision,
    attention,
    download_if_missing,
    seed,
    max_new_tokens,
    top_p,
    top_k,
    temperature,
    repetition_penalty,
    output_cleanup,
    ptbr_mode="Native PT-BR Hybrid (recommended)",
    clone_profile="Maximum Similarity",
    candidate_count=4,
    subtalker_temperature=0.65,
    progress_callback=None,
):
    """
    Qwen-only PT-BR hybrid:
      1) identity_audio supplies speaker identity;
      2) dedicated PT-BR checkpoint supplies Brazilian codec/prosody + performance;
      3) Qwen Base 1.7B generates target text and ranks candidates by identity.

    This avoids Chatterbox/OpenVoice while preserving selected/designed identity.
    """
    _emit_progress_callback(progress_callback, 0.04, "Generating native PT-BR anchor")
    accent_anchor = _generate_ptbr_anchor_audio(
        ref_text=str(identity_text),
        checkpoint_step=str(checkpoint_step),
        device=device,
        precision=precision,
        attention=attention,
        download_if_missing=bool(download_if_missing),
        seed=int(seed),
        style_instruct=str(voice_instruction or ""),
    )

    _emit_progress_callback(progress_callback, 0.24, "PT-BR anchor ready")
    _emit_progress_callback(progress_callback, 0.28, "Loading Qwen Base")
    model = load_model("Base", "1.7B", device, precision, attention, "")
    _emit_progress_callback(progress_callback, 0.36, "Qwen Base ready")
    try:
        preset = _ptbr_mode_settings(ptbr_mode)
        effective_profile = preset["clone_profile"] or str(clone_profile)
        effective_count = (
            int(preset["candidate_count"])
            if preset["candidate_count"] is not None
            else int(candidate_count)
        )
        effective_subtalker = (
            float(preset["subtalker_temperature"])
            if preset["subtalker_temperature"] is not None
            else float(subtalker_temperature)
        )

        result = generate_hq_voice_clone(
            model=model,
            ref_audio_tuple=identity_audio,
            ref_text=str(identity_text),
            target_text=str(target_text),
            language="portuguese",
            accent_anchor_audio_tuple=accent_anchor,
            accent_anchor_text=str(identity_text),
            seed=int(seed),
            max_new_tokens=int(max_new_tokens),
            top_p=float(top_p),
            top_k=int(top_k),
            temperature=float(temperature),
            repetition_penalty=float(repetition_penalty),
            x_vector_only=False,
            clone_profile=effective_profile,
            candidate_count=max(1, min(effective_count, 6)),
            reference_processing="Original",
            subtalker_temperature=effective_subtalker,
            progress_callback=_map_progress_callback(progress_callback, 0.36, 0.94),
        )
    finally:
        try:
            del model
        except Exception:
            pass

    _emit_progress_callback(progress_callback, 0.96, "Cleaning output audio")
    audio = _to_comfy_audio(result.wavs, result.sample_rate, output_cleanup)
    _emit_progress_callback(progress_callback, 1.0, "Audio ready")
    return audio


def _seed_everything(seed: int):
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


PROGRESS_TOTAL = 100


def _progress(total=PROGRESS_TOTAL):
    return ProgressBar(int(total)) if ProgressBar is not None else None


def _pupdate(pbar, step, total=PROGRESS_TOTAL):
    """Best-effort ComfyUI progress update. UI feedback must never break TTS."""
    if pbar is not None:
        try:
            value = max(0, min(int(total), int(round(float(step)))))
            pbar.update_absolute(value, int(total), None)
        except Exception:
            pass


def _emit_progress_callback(callback, fraction, stage=""):
    if callback is None:
        return
    try:
        callback(max(0.0, min(1.0, float(fraction))), str(stage))
    except Exception:
        pass


def _map_progress_callback(callback, start, end):
    """Map a child 0..1 progress callback into a parent 0..1 interval."""
    if callback is None:
        return None
    start = float(start)
    end = float(end)
    span = max(0.0, end - start)

    def _mapped(fraction, stage=""):
        _emit_progress_callback(callback, start + span * max(0.0, min(1.0, float(fraction))), stage)

    return _mapped


def _node_progress_callback(pbar):
    def _callback(fraction, stage=""):
        _pupdate(pbar, float(fraction) * PROGRESS_TOTAL, PROGRESS_TOTAL)
    return _callback


def _audio_to_model_tuple(audio: Dict[str, Any]):
    if not isinstance(audio, dict) or "waveform" not in audio:
        raise RuntimeError("Reference audio must be a ComfyUI AUDIO input.")

    waveform = audio["waveform"]
    sr = int(audio.get("sample_rate", 0))
    if sr <= 0:
        raise RuntimeError("Reference audio has no valid sample_rate.")

    if isinstance(waveform, torch.Tensor):
        w = waveform.detach().float().cpu()
        if w.ndim == 3:
            w = w[0]
        if w.ndim == 2:
            w = w.mean(dim=0)
        elif w.ndim != 1:
            w = w.reshape(-1)
        arr = w.numpy().astype(np.float32, copy=False)
    else:
        arr = np.asarray(waveform, dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[0]
        if arr.ndim == 2:
            arr = arr.mean(axis=0)
        arr = arr.reshape(-1).astype(np.float32, copy=False)

    return (arr, sr)


def _to_comfy_audio(
    wavs,
    sr,
    output_cleanup="Clean Voice (recommended)",
):
    if not isinstance(wavs, (list, tuple)) or not wavs:
        raise RuntimeError("Qwen3-TTS returned no audio.")

    clean_wav, clean_meta = clean_generated_audio(
        wavs[0],
        int(sr),
        mode=str(output_cleanup),
    )

    if str(output_cleanup) != "Off":
        print(
            "[Lyonir Qwen3-TTS] Output cleanup: "
            f"{output_cleanup} | noise confidence "
            f"{clean_meta['noise_confidence']:.2f} | peak "
            f"{clean_meta['before_peak']:.4f} -> "
            f"{clean_meta['after_peak']:.4f}"
        )

    tensor = torch.from_numpy(np.ascontiguousarray(clean_wav)).float()
    if tensor.ndim == 1:
        tensor = tensor.unsqueeze(0).unsqueeze(0)
    elif tensor.ndim == 2:
        tensor = tensor.unsqueeze(0)

    return {"waveform": tensor, "sample_rate": int(sr)}




def _voice_instruction_input(default=""):
    return (
        "STRING",
        {
            "multiline": True,
            "default": default,
            "placeholder": (
                "Descreva a performance em linguagem natural. Ex.: "
                "'Fale muito rápido, com muita energia e entusiasmo.' / "
                "'Fale devagar, triste, com voz baixa e pausas longas.' / "
                "'Fale com muita raiva, tensão e agressividade.'"
            ),
        },
    )


def _unified_instruction_input(default=""):
    return (
        "STRING",
        {
            "multiline": True,
            "default": default,
            "placeholder": (
                "Use uma única instrução para identidade e performance. Ex.: "
                "'Homem adulto, voz grave e cinematográfica, falando rápido, com raiva controlada, "
                "alta energia e pausas curtas.'"
            ),
            "tooltip": (
                "Single instruction used for voice identity/design and delivery/performance. "
                "In PT-BR it is routed to both the identity stage and the Brazilian prosody/performance stage."
            ),
        },
    )


def _combine_performance_instructions(*parts):
    clean = [str(x).strip() for x in parts if str(x or "").strip()]
    return " ".join(clean)


def _ptbr_mode_settings(mode: str):
    """
    Translate the friendly PT-BR quality presets into Qwen Base clone settings.

    All modes keep the Brazilian fine-tune as the pronunciation/prosody donor.
    None of these PT-BR modes falls back to generic Portuguese as the accent
    source.
    """
    value = str(mode or "").strip()

    if value == "Native PT-BR Natural":
        return {
            "clone_profile": "Balanced",
            "candidate_count": 3,
            "subtalker_temperature": 0.78,
        }

    if value == "Native PT-BR Maximum Identity":
        return {
            "clone_profile": "Maximum Similarity",
            "candidate_count": 6,
            "subtalker_temperature": 0.62,
        }

    if value == "Native PT-BR Custom (advanced)":
        return {
            "clone_profile": None,
            "candidate_count": None,
            "subtalker_temperature": None,
        }

    # Default and backward-compatible fallback.
    return {
        "clone_profile": "Maximum Similarity",
        "candidate_count": 4,
        "subtalker_temperature": 0.65,
    }



def _common_optional():
    return {
        "seed": (
            "INT",
            {
                "default": 0,
                "min": 0,
                "max": 0xFFFFFFFFFFFFFFFF,
                "control_after_generate": True,
            },
        ),
        "max_new_tokens": ("INT", {"default": 2048, "min": 256, "max": 8192, "step": 256}),
        "top_p": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
        "top_k": ("INT", {"default": 50, "min": 0, "max": 200, "step": 1}),
        "temperature": ("FLOAT", {"default": 0.9, "min": 0.1, "max": 2.0, "step": 0.05}),
        "repetition_penalty": ("FLOAT", {"default": 1.05, "min": 1.0, "max": 2.0, "step": 0.05}),
        "attention": (ATTENTION, {"default": "auto"}),
        "output_cleanup": (
            OUTPUT_CLEANUP_MODES,
            {
                "default": "Clean Voice (recommended)",
                "tooltip": "Post-synthesis cleanup for hiss/background noise. Strong Clean is more aggressive; Off returns the raw model output.",
            },
        ),
        "unload_model_after_generate": ("BOOLEAN", {"default": False}),
        "custom_model_path": (
            "STRING",
            {
                "default": "",
                "placeholder": "Optional local model folder. Leave blank for models/qwen-tts or Hugging Face.",
            },
        ),
    }


class LyonirQwen3TTSVoiceDesign:
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        optional = _common_optional()
        optional.update(
            {
                "ptbr_engine": (
                    PTBR_ENGINES,
                    {
                        "default": "Native PT-BR Hybrid (recommended)",
                        "tooltip": (
                            "All PT-BR modes use the dedicated Brazilian checkpoint as the accent/prosody source."
                        ),
                    },
                ),
                "ptbr_checkpoint_step": (["15000", "10000", "5000"], {"default": "15000"}),
                "download_ptbr_if_missing": ("BOOLEAN", {"default": True}),
            }
        )
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "Olá! Esta é uma voz em português brasileiro."}),
                "instruction": _unified_instruction_input(
                    "Homem adulto, voz natural, cinematográfica, clara e expressiva. "
                    "Fale de forma natural, expressiva e cinematográfica."
                ),
                "model_choice": (["1.7B"], {"default": "1.7B"}),
                "device": (DEVICES, {"default": "auto"}),
                "precision": (PRECISIONS, {"default": "bf16"}),
                "language": (LANGUAGES, {"default": "Portuguese (Brazil)"}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "generate"
    CATEGORY = "Lyonir Studio/Qwen3-TTS"
    DESCRIPTION = (
        "Voice Design with one unified Instruction field for voice identity, timbre, emotion, speed, energy and acting. "
        "Native Qwen PT-BR is the Brazil-first quality renderer."
    )

    def generate(
        self,
        text,
        model_choice,
        device,
        precision,
        language,
        instruction="",
        ptbr_engine="Native PT-BR Hybrid (recommended)",
        ptbr_checkpoint_step="15000",
        download_ptbr_if_missing=True,
        cosyvoice_speed=1.0,
        download_cosyvoice_if_missing=True,
        seed=0,
        max_new_tokens=2048,
        top_p=1.0,
        top_k=50,
        temperature=0.9,
        repetition_penalty=1.05,
        attention="auto",
        output_cleanup="Clean Voice (recommended)",
        unload_model_after_generate=False,
        custom_model_path="",
        **kwargs,
    ):
        if not str(text).strip():
            raise RuntimeError("Text is required.")

        pbar = _progress()
        progress_cb = _node_progress_callback(pbar)
        _pupdate(pbar, 3)

        # v1.0.1 exposes only one public Instruction input. Keep compatibility
        # with API/prompts that may still provide the old v1.0.0 field names.
        instruction_text = str(instruction or "").strip()
        if not instruction_text:
            instruction_text = _combine_performance_instructions(
                kwargs.get("instruct", ""),
                kwargs.get("voice_instruction", ""),
            )
        if not instruction_text:
            raise RuntimeError("Voice Design requires an Instruction.")

        if str(language) == "Portuguese (Brazil)":
            # The same unified instruction is applied to both stages:
            # VoiceDesign identity + dedicated PT-BR prosody/performance anchor.
            _pupdate(pbar, 8)
            ensure_backend()
            _pupdate(pbar, 12)
            identity_audio = _generate_voice_design_identity_audio(
                instruct=instruction_text,
                device=device,
                precision=precision,
                attention=attention,
                seed=int(seed),
                custom_model_path=custom_model_path,
            )
            _pupdate(pbar, 35)
            audio = _render_qwen_ptbr_hybrid_from_identity(
                identity_audio=identity_audio,
                identity_text=IDENTITY_REFERENCE_TEXT_PTBR,
                target_text=str(text),
                voice_instruction=instruction_text,
                checkpoint_step=str(ptbr_checkpoint_step),
                device=device,
                precision=precision,
                attention=attention,
                download_if_missing=bool(download_ptbr_if_missing),
                seed=int(seed),
                max_new_tokens=int(max_new_tokens),
                top_p=float(top_p),
                top_k=int(top_k),
                temperature=float(temperature),
                repetition_penalty=float(repetition_penalty),
                output_cleanup=output_cleanup,
                ptbr_mode=str(ptbr_engine),
                clone_profile="Maximum Similarity",
                candidate_count=4,
                subtalker_temperature=0.65,
                progress_callback=_map_progress_callback(progress_cb, 0.35, 0.99),
            )
            _pupdate(pbar, 100)
            if unload_model_after_generate:
                unload_all()
            return (audio,)

        # Other languages: official Qwen VoiceDesign path.
        _pupdate(pbar, 10)
        ensure_backend()
        _pupdate(pbar, 18)
        model = load_model("VoiceDesign", model_choice, device, precision, attention, custom_model_path)
        _pupdate(pbar, 35)
        _seed_everything(seed)
        effective_instruct = _with_brazilian_instruction(language, instruction_text)
        _pupdate(pbar, 42)
        try:
            wavs, sr = model.generate_voice_design(
                text=str(text),
                instruct=effective_instruct,
                language=_qwen_language(language),
                max_new_tokens=int(max_new_tokens),
                top_p=float(top_p),
                top_k=int(top_k),
                temperature=float(temperature),
                repetition_penalty=float(repetition_penalty),
            )
        finally:
            if unload_model_after_generate:
                unload_all()
        _pupdate(pbar, 92)
        audio = _to_comfy_audio(wavs, sr, output_cleanup)
        _pupdate(pbar, 100)
        return (audio,)


class LyonirQwen3TTSVoiceClone:
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        optional = _common_optional()
        optional.update(
            {
                "voice_instruction": _voice_instruction_input(
                    "Descreva exatamente como a fala deve ser interpretada. Quando preenchida, "
                    "o Lyonir usa uma rota Instruction-First para maximizar ritmo, emoção, energia, "
                    "ênfase, pausas e entonação, preservando a identidade da referência."
                ),
                "brazilian_clone_mode": (
                    BRAZILIAN_CLONE_MODES,
                    {
                        "default": "Native PT-BR Hybrid (recommended)",
                        "tooltip": (
                            "Usado apenas quando language = Portuguese (Brazil). "
                            "Todos os modos PT-BR usam o checkpoint brasileiro; "
                            "nenhum usa o português genérico como fonte final de sotaque."
                        ),
                    },
                ),
                "official_clone_mode": (
                    OFFICIAL_CLONE_MODES,
                    {
                        "default": "Official Qwen ICL Clone (recommended)",
                        "tooltip": (
                            "Usado nos idiomas originais do Qwen. ICL usa áudio + "
                            "transcrição para maior fidelidade; Speaker-Only usa apenas "
                            "a identidade vocal."
                        ),
                    },
                ),
                "ptbr_checkpoint_step": (
                    ["15000", "10000", "5000"],
                    {
                        "default": "15000",
                        "tooltip": "Checkpoint 15000 é o recomendado para PT-BR.",
                    },
                ),
                "download_ptbr_if_missing": ("BOOLEAN", {"default": True}),
                "ref_text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "placeholder": (
                            "Transcrição EXATA do ref_audio. Obrigatória no PT-BR Hybrid "
                            "e no Official Qwen ICL Clone; opcional no Speaker-Only."
                        ),
                    },
                ),
                "clone_profile": (
                    CLONE_PROFILES,
                    {
                        "default": "Maximum Similarity",
                        "tooltip": (
                            "Advanced setting. PT-BR Custom respeita este campo; "
                            "os presets PT-BR recomendados usam configurações próprias."
                        ),
                    },
                ),
                "candidate_count": (
                    "INT",
                    {
                        "default": 4,
                        "min": 1,
                        "max": 6,
                        "step": 1,
                    },
                ),
                "reference_processing": (
                    REFERENCE_PROCESSING,
                    {"default": "HQ Clean (recommended)"},
                ),
                "subtalker_temperature": (
                    "FLOAT",
                    {
                        "default": 0.65,
                        "min": 0.1,
                        "max": 2.0,
                        "step": 0.05,
                    },
                ),
            }
        )
        return {
            "required": {
                "ref_audio": ("AUDIO",),
                "target_text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "Olá! Esta é uma clonagem de voz em português brasileiro.",
                    },
                ),
                "model_choice": (
                    ["1.7B", "0.6B"],
                    {
                        "default": "1.7B",
                        "tooltip": (
                            "PT-BR Hybrid usa Base 1.7B internamente para máxima qualidade. "
                            "0.6B é aplicado ao clone oficial dos outros idiomas."
                        ),
                    },
                ),
                "device": (DEVICES, {"default": "auto"}),
                "precision": (PRECISIONS, {"default": "bf16"}),
                "language": (LANGUAGES, {"default": "Portuguese (Brazil)"}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "generate"
    CATEGORY = "Lyonir Studio/Qwen3-TTS"
    DESCRIPTION = (
        "Multilingual Qwen3-TTS Voice Clone. Voice Instruction uses an Instruction-First "
        "performance guide while the real reference supplies speaker identity. Portuguese "
        "(Brazil) also keeps the dedicated Brazilian pronunciation/prosody anchor."
    )

    def generate(
        self,
        ref_audio,
        target_text,
        model_choice="1.7B",
        device="auto",
        precision="bf16",
        language="Portuguese (Brazil)",
        voice_instruction="",
        brazilian_clone_mode="Native PT-BR Hybrid (recommended)",
        official_clone_mode="Official Qwen ICL Clone (recommended)",
        ptbr_checkpoint_step="15000",
        download_ptbr_if_missing=True,
        ref_text="",
        clone_profile="Maximum Similarity",
        candidate_count=4,
        reference_processing="HQ Clean (recommended)",
        subtalker_temperature=0.65,
        seed=0,
        max_new_tokens=2048,
        top_p=1.0,
        top_k=50,
        temperature=0.9,
        repetition_penalty=1.05,
        attention="auto",
        output_cleanup="Clean Voice (recommended)",
        unload_model_after_generate=False,
        custom_model_path="",
        **kwargs,
    ):
        if not str(target_text).strip():
            raise RuntimeError("Target text is required.")

        pbar = _progress()
        progress_cb = _node_progress_callback(pbar)
        _pupdate(pbar, 3)
        audio_tuple = _audio_to_model_tuple(ref_audio)
        _pupdate(pbar, 8)

        # --------------------------------------------------------------
        # Brazil-first path. This NEVER uses generic Qwen Portuguese as
        # the accent/prosody donor.
        # --------------------------------------------------------------
        if str(language) == "Portuguese (Brazil)":
            if not str(ref_text).strip():
                raise RuntimeError(
                    "Portuguese (Brazil) requires ref_text to be the exact "
                    "transcript of the reference audio."
                )

            performance = str(voice_instruction or "").strip()
            instruction_active = bool(performance)

            # Instruction-First route (v1.2):
            # - the native PT-BR checkpoint always provides the Brazilian anchor;
            # - when Voice Instruction is present, the anchor speaks target_text so the
            #   requested pace/pauses/emphasis line up with the final sentence;
            # - VoiceDesign additionally creates a strong same-text performance guide.
            #   Its speaker identity is discarded; only performance/prosody is used.
            anchor_text = str(target_text) if instruction_active else str(ref_text)

            _pupdate(pbar, 12)
            accent_anchor = _generate_ptbr_anchor_audio(
                ref_text=anchor_text,
                checkpoint_step=str(ptbr_checkpoint_step),
                device=device,
                precision=precision,
                attention=attention,
                download_if_missing=bool(download_ptbr_if_missing),
                seed=int(seed),
                style_instruct=performance,
            )
            _pupdate(pbar, 26)

            performance_guide = None
            if instruction_active:
                try:
                    performance_guide = _generate_instruction_performance_guide(
                        text=str(target_text),
                        language=str(language),
                        instruction=performance,
                        device=device,
                        precision=precision,
                        attention=attention,
                        seed=int(seed),
                        max_new_tokens=int(max_new_tokens),
                    )
                    print("[Lyonir Qwen3-TTS] Instruction-First VoiceDesign performance guide active.")
                except Exception as exc:
                    # Never make Voice Instruction unusable because the optional VoiceDesign
                    # guide failed; the strengthened native PT-BR anchor remains active.
                    print(
                        "[Lyonir Qwen3-TTS] VoiceDesign performance guide unavailable; "
                        f"using strengthened PT-BR guide only: {exc}"
                    )
                    performance_guide = None
            _pupdate(pbar, 38)

            ensure_backend()
            _pupdate(pbar, 42)
            model = load_model(
                "Base",
                "1.7B",
                device,
                precision,
                attention,
                custom_model_path,
            )
            _pupdate(pbar, 48)

            preset = _ptbr_mode_settings(brazilian_clone_mode)
            effective_profile = preset["clone_profile"] or str(clone_profile)
            effective_count = (
                int(preset["candidate_count"])
                if preset["candidate_count"] is not None
                else int(candidate_count)
            )
            effective_subtalker = (
                float(preset["subtalker_temperature"])
                if preset["subtalker_temperature"] is not None
                else float(subtalker_temperature)
            )

            # When Voice Instruction is present we intentionally open the sampling
            # space and generate the maximum candidate set. The final selector still
            # enforces a strict speaker-identity floor before rewarding performance.
            if instruction_active:
                effective_profile = "Balanced"
                effective_count = 6
                effective_subtalker = max(float(effective_subtalker), 0.78)

            try:
                result = generate_hq_voice_clone(
                    model=model,
                    ref_audio_tuple=audio_tuple,
                    ref_text=str(ref_text),
                    target_text=str(target_text),
                    language="portuguese",
                    accent_anchor_audio_tuple=accent_anchor,
                    accent_anchor_text=anchor_text,
                    alternate_anchor_audio_tuple=performance_guide,
                    alternate_anchor_text=(str(target_text) if performance_guide is not None else None),
                    performance_guide_audio_tuple=(performance_guide or (accent_anchor if instruction_active else None)),
                    seed=int(seed),
                    max_new_tokens=int(max_new_tokens),
                    top_p=float(top_p),
                    top_k=int(top_k),
                    temperature=float(temperature),
                    repetition_penalty=float(repetition_penalty),
                    x_vector_only=False,
                    clone_profile=effective_profile,
                    candidate_count=max(1, min(effective_count, 6)),
                    reference_processing=str(reference_processing),
                    subtalker_temperature=effective_subtalker,
                    progress_callback=_map_progress_callback(progress_cb, 0.48, 0.94),
                )
            finally:
                if unload_model_after_generate:
                    unload_all()

            _pupdate(pbar, 96)
            audio = _to_comfy_audio(
                result.wavs,
                result.sample_rate,
                output_cleanup,
            )
            _pupdate(pbar, 100)
            return (audio,)

        # --------------------------------------------------------------
        # Instruction-First multilingual route. The official Base clone API has no
        # native instruct argument, so VoiceDesign creates a same-text performance
        # guide and the real reference contributes only the speaker embedding.
        # --------------------------------------------------------------
        performance = str(voice_instruction or "").strip()
        if performance:
            _pupdate(pbar, 14)
            guide = _generate_instruction_performance_guide(
                text=str(target_text),
                language=str(language),
                instruction=performance,
                device=device,
                precision=precision,
                attention=attention,
                seed=int(seed),
                max_new_tokens=int(max_new_tokens),
            )
            _pupdate(pbar, 36)
            ensure_backend()
            model = load_model(
                "Base",
                str(model_choice),
                device,
                precision,
                attention,
                custom_model_path,
            )
            _pupdate(pbar, 46)
            try:
                result = generate_hq_voice_clone(
                    model=model,
                    ref_audio_tuple=audio_tuple,
                    ref_text=str(ref_text),
                    target_text=str(target_text),
                    language=_qwen_language(language),
                    accent_anchor_audio_tuple=guide,
                    accent_anchor_text=str(target_text),
                    performance_guide_audio_tuple=guide,
                    seed=int(seed),
                    max_new_tokens=int(max_new_tokens),
                    top_p=float(top_p),
                    top_k=int(top_k),
                    temperature=float(temperature),
                    repetition_penalty=float(repetition_penalty),
                    x_vector_only=False,
                    clone_profile="Balanced",
                    candidate_count=6,
                    reference_processing=str(reference_processing),
                    subtalker_temperature=max(float(subtalker_temperature), 0.78),
                    progress_callback=_map_progress_callback(progress_cb, 0.46, 0.94),
                )
            finally:
                if unload_model_after_generate:
                    unload_all()

            _pupdate(pbar, 96)
            audio = _to_comfy_audio(result.wavs, result.sample_rate, output_cleanup)
            _pupdate(pbar, 100)
            return (audio,)

        # --------------------------------------------------------------
        # Original Qwen multilingual clone path.
        # --------------------------------------------------------------
        x_vector_only = str(official_clone_mode) == "Official Qwen Speaker-Only"
        if not x_vector_only and not str(ref_text).strip():
            raise RuntimeError(
                "Official Qwen ICL Clone requires ref_text to be the exact "
                "transcript of the reference audio. Choose Speaker-Only if "
                "you do not have the transcript."
            )

        _pupdate(pbar, 15)
        ensure_backend()
        _pupdate(pbar, 22)
        model = load_model(
            "Base",
            str(model_choice),
            device,
            precision,
            attention,
            custom_model_path,
        )
        _pupdate(pbar, 34)

        try:
            result = generate_hq_voice_clone(
                model=model,
                ref_audio_tuple=audio_tuple,
                ref_text=str(ref_text),
                target_text=str(target_text),
                language=_qwen_language(language),
                accent_anchor_audio_tuple=None,
                accent_anchor_text=None,
                seed=int(seed),
                max_new_tokens=int(max_new_tokens),
                top_p=float(top_p),
                top_k=int(top_k),
                temperature=float(temperature),
                repetition_penalty=float(repetition_penalty),
                x_vector_only=bool(x_vector_only),
                clone_profile=str(clone_profile),
                candidate_count=max(1, min(int(candidate_count), 6)),
                reference_processing=str(reference_processing),
                subtalker_temperature=float(subtalker_temperature),
                progress_callback=_map_progress_callback(progress_cb, 0.34, 0.94),
            )
        finally:
            if unload_model_after_generate:
                unload_all()

        _pupdate(pbar, 96)
        audio = _to_comfy_audio(
            result.wavs,
            result.sample_rate,
            output_cleanup,
        )
        _pupdate(pbar, 100)
        return (audio,)


class LyonirQwen3TTSCustomVoice:
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        optional = _common_optional()
        optional.update(
            {
                "instruction": _unified_instruction_input(""),
                "ptbr_engine": (
                    PTBR_ENGINES,
                    {
                        "default": "Native PT-BR Hybrid (recommended)",
                        "tooltip": (
                            "All PT-BR modes use the dedicated Brazilian checkpoint as the accent/prosody source."
                        ),
                    },
                ),
                "ptbr_checkpoint_step": (["15000", "10000", "5000"], {"default": "15000"}),
                "download_ptbr_if_missing": ("BOOLEAN", {"default": True}),
                "custom_speaker_name": (
                    "STRING",
                    {
                        "default": "",
                        "placeholder": "Optional speaker id for a custom Qwen CustomVoice model.",
                    },
                ),
            }
        )
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "Olá! Esta é uma voz brasileira nativa."}),
                "speaker": (SPEAKERS, {"default": "Leonardo"}),
                "model_choice": (["1.7B", "0.6B"], {"default": "1.7B"}),
                "device": (DEVICES, {"default": "auto"}),
                "precision": (PRECISIONS, {"default": "bf16"}),
                "language": (LANGUAGES, {"default": "Portuguese (Brazil)"}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "generate"
    CATEGORY = "Lyonir Studio/Qwen3-TTS"
    DESCRIPTION = (
        "Custom Voice with one unified Instruction field for voice character, emotion, speed, energy and acting. "
        "Leonardo is always forced to an adult male Aiden-based identity."
    )

    def generate(
        self,
        text,
        speaker,
        model_choice,
        device,
        precision,
        language,
        instruction="",
        ptbr_engine="Native PT-BR Hybrid (recommended)",
        ptbr_checkpoint_step="15000",
        download_ptbr_if_missing=True,
        cosyvoice_speed=1.0,
        download_cosyvoice_if_missing=True,
        custom_speaker_name="",
        seed=0,
        max_new_tokens=2048,
        top_p=1.0,
        top_k=50,
        temperature=0.9,
        repetition_penalty=1.05,
        attention="auto",
        output_cleanup="Clean Voice (recommended)",
        unload_model_after_generate=False,
        custom_model_path="",
        **kwargs,
    ):
        if not str(text).strip():
            raise RuntimeError("Text is required.")

        pbar = _progress()
        progress_cb = _node_progress_callback(pbar)
        _pupdate(pbar, 3)

        # v1.0.1 exposes only one public Instruction input. Legacy v1.0.0
        # API field names are still accepted through kwargs when available.
        instruction_text = str(instruction or "").strip()
        if not instruction_text:
            instruction_text = _combine_performance_instructions(
                kwargs.get("instruct", ""),
                kwargs.get("voice_instruction", ""),
            )

        combined = instruction_text

        # Leonardo's identity is always explicitly male.
        if str(speaker) == "Leonardo":
            combined = _combine_performance_instructions(
                "Adult male voice. Clearly masculine timbre. The speaker must remain male and must not be feminized.",
                combined,
            )

        if str(language) == "Portuguese (Brazil)":
            # The same unified instruction is applied to both stages:
            # selected Qwen identity + native PT-BR prosody/performance.
            _pupdate(pbar, 8)
            ensure_backend()
            _pupdate(pbar, 12)
            if str(speaker) == "Leonardo":
                print(
                    "[Lyonir Qwen3-TTS] Leonardo: enforcing adult MALE Aiden identity "
                    "+ native PT-BR hybrid prosody."
                )

            identity_audio = _generate_custom_identity_audio(
                speaker=str(speaker),
                model_choice=str(model_choice),
                user_instruct=instruction_text,
                device=device,
                precision=precision,
                attention=attention,
                seed=int(seed),
                custom_model_path=custom_model_path,
                custom_speaker_name=str(custom_speaker_name),
            )
            _pupdate(pbar, 35)

            audio = _render_qwen_ptbr_hybrid_from_identity(
                identity_audio=identity_audio,
                identity_text=IDENTITY_REFERENCE_TEXT_PTBR,
                target_text=str(text),
                voice_instruction=instruction_text,
                checkpoint_step=str(ptbr_checkpoint_step),
                device=device,
                precision=precision,
                attention=attention,
                download_if_missing=bool(download_ptbr_if_missing),
                seed=int(seed),
                max_new_tokens=int(max_new_tokens),
                top_p=float(top_p),
                top_k=int(top_k),
                temperature=float(temperature),
                repetition_penalty=float(repetition_penalty),
                output_cleanup=output_cleanup,
                ptbr_mode=str(ptbr_engine),
                clone_profile="Maximum Similarity",
                candidate_count=4,
                subtalker_temperature=0.65,
                progress_callback=_map_progress_callback(progress_cb, 0.35, 0.99),
            )
            _pupdate(pbar, 100)
            if unload_model_after_generate:
                unload_all()
            return (audio,)

        # Non-PT-BR normal Qwen CustomVoice.
        target_speaker = (
            LEONARDO_IDENTITY_SPEAKER
            if str(speaker) == "Leonardo"
            else (
                str(custom_speaker_name).strip()
                if str(custom_speaker_name).strip()
                else str(speaker).lower().replace(" ", "_")
            )
        )
        _pupdate(pbar, 10)
        ensure_backend()
        _pupdate(pbar, 18)
        model = load_model("CustomVoice", model_choice, device, precision, attention, custom_model_path)
        _pupdate(pbar, 35)
        _seed_everything(seed)
        _pupdate(pbar, 42)
        try:
            wavs, sr = model.generate_custom_voice(
                text=str(text),
                speaker=target_speaker,
                language=_qwen_language(language),
                instruct=combined or None,
                max_new_tokens=int(max_new_tokens),
                top_p=float(top_p),
                top_k=int(top_k),
                temperature=float(temperature),
                repetition_penalty=float(repetition_penalty),
            )
        finally:
            if unload_model_after_generate:
                unload_all()
        _pupdate(pbar, 92)
        audio = _to_comfy_audio(wavs, sr, output_cleanup)
        _pupdate(pbar, 100)
        return (audio,)


class LyonirQwen3TTSPTBR:
    """
    Dedicated Brazilian Portuguese node backed by an actual PT-BR fine-tuned
    Qwen3-TTS checkpoint rather than a language-label/prompt alias.
    """

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "Olá! Esta voz utiliza um modelo Qwen3-TTS treinado em português brasileiro.",
                    },
                ),
                "checkpoint_step": (
                    ["15000", "10000", "5000"],
                    {
                        "default": "15000",
                        "tooltip": "Public PT-BR checkpoints. 15000 is the latest available checkpoint in the repository.",
                    },
                ),
                "device": (DEVICES, {"default": "auto"}),
                "precision": (PRECISIONS, {"default": "bf16"}),
            },
            "optional": {
                "instruct": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "placeholder": "Optional emotion/style instruction. The model language and speaker stay locked to PT-BR / pb_sotaque.",
                    },
                ),
                "download_if_missing": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "First use downloads the selected complete checkpoint from Hugging Face. It is a large model.",
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "control_after_generate": True,
                    },
                ),
                "max_new_tokens": ("INT", {"default": 2048, "min": 256, "max": 8192, "step": 256}),
                "top_p": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "top_k": ("INT", {"default": 50, "min": 0, "max": 200, "step": 1}),
                "temperature": ("FLOAT", {"default": 0.9, "min": 0.1, "max": 2.0, "step": 0.05}),
                "repetition_penalty": ("FLOAT", {"default": 1.05, "min": 1.0, "max": 2.0, "step": 0.05}),
                "attention": (ATTENTION, {"default": "sdpa"}),
                "output_cleanup": (
                    OUTPUT_CLEANUP_MODES,
                    {
                        "default": "Clean Voice (recommended)",
                        "tooltip": "Post-synthesis cleanup for hiss/background noise. Strong Clean is more aggressive.",
                    },
                ),
                "unload_model_after_generate": ("BOOLEAN", {"default": False}),
                "custom_model_path": (
                    "STRING",
                    {
                        "default": "",
                        "placeholder": "Optional local PT-BR checkpoint folder; overrides checkpoint_step/download.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "generate"
    CATEGORY = "Lyonir Studio/Qwen3-TTS"
    DESCRIPTION = (
        "Dedicated PT-BR node using the acidente/fala_pb_checkpoints Qwen3-TTS fine-tune "
        "(Paraiba accent, speaker pb_sotaque)."
    )

    def generate(
        self,
        text,
        checkpoint_step,
        device,
        precision,
        instruct="",
        download_if_missing=True,
        seed=0,
        max_new_tokens=2048,
        top_p=1.0,
        top_k=50,
        temperature=0.9,
        repetition_penalty=1.05,
        attention="sdpa",
        output_cleanup="Clean Voice (recommended)",
        unload_model_after_generate=False,
        custom_model_path="",
    ):
        if not str(text).strip():
            raise RuntimeError("Text is required.")

        pbar = _progress()
        _pupdate(pbar, 3)
        ensure_backend()
        _pupdate(pbar, 12)

        model = load_ptbr_model(
            checkpoint_step=str(checkpoint_step),
            device=device,
            precision=precision,
            attention=attention,
            download_if_missing=bool(download_if_missing),
            custom_model_path=custom_model_path,
        )
        _seed_everything(seed)
        _pupdate(pbar, 35)

        try:
            _pupdate(pbar, 42)
            wavs, sr = model.generate_custom_voice(
                text=str(text),
                speaker=PTBR_SPEAKER,
                language=PTBR_LANGUAGE,
                instruct=str(instruct).strip() or None,
                max_new_tokens=int(max_new_tokens),
                top_p=float(top_p),
                top_k=int(top_k),
                temperature=float(temperature),
                repetition_penalty=float(repetition_penalty),
            )
        except Exception as e:
            raise RuntimeError(
                "PT-BR generation failed. The dedicated checkpoint expects "
                f"speaker='{PTBR_SPEAKER}' and language='{PTBR_LANGUAGE}'. Error: {e}"
            ) from e

        _pupdate(pbar, 92)
        audio = _to_comfy_audio(wavs, sr, output_cleanup)
        _pupdate(pbar, 100)
        if unload_model_after_generate:
            unload_all()
        return (audio,)
