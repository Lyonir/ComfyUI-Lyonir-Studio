from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import folder_paths
from aiohttp import web
from server import PromptServer


_HISTORY_DIRNAME = ".lyonir_video_gallery"
_THUMB_DIRNAME = "thumbs"
_PREVIEW_DIRNAME = "previews"
_MANIFEST_VERSION = 4
_MAX_MANIFEST_ENTRIES = 500
_HISTORY_LIMIT = 12

_BIT_DEPTHS = [
    "Auto (format)",
    "8-bit",
    "10-bit",
    "12-bit",
    "16-bit",
]


def _safe_node_id(value: Any) -> str:
    text = str(value if value is not None else "unknown")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return text or "unknown"


def _safe_subfolder(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().strip("/")
    if not text:
        return ""
    parts: list[str] = []
    for part in text.split("/"):
        part = part.strip()
        if not part or part in {".", ".."}:
            continue
        part = re.sub(r"[<>:\"|?*]+", "_", part)
        parts.append(part)
    return "/".join(parts)


def _history_dir() -> Path:
    path = Path(folder_paths.get_output_directory()) / _HISTORY_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path(node_id: Any) -> Path:
    return _history_dir() / f"node_{_safe_node_id(node_id)}.json"


def _root_for_type(media_type: str) -> Path:
    return Path(folder_paths.get_temp_directory() if media_type == "temp" else folder_paths.get_output_directory())


def _resolve_media_file(media_type: Any, subfolder: Any, filename: Any) -> Path | None:
    root = _root_for_type(str(media_type or "output")).resolve()
    safe_subfolder = _safe_subfolder(subfolder)
    safe_filename = os.path.basename(str(filename or ""))
    if not safe_filename:
        return None
    candidate = (root / safe_subfolder / safe_filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _load_manifest(node_id: Any) -> dict[str, Any]:
    path = _manifest_path(node_id)
    if not path.exists():
        return {"version": _MANIFEST_VERSION, "node_id": str(node_id), "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("entries", []) if isinstance(data, dict) else []
        if not isinstance(entries, list):
            entries = []
        return {
            "version": _MANIFEST_VERSION,
            "node_id": str(node_id),
            "entries": entries,
        }
    except Exception:
        return {"version": _MANIFEST_VERSION, "node_id": str(node_id), "entries": []}


def _save_manifest(node_id: Any, data: dict[str, Any]) -> None:
    path = _manifest_path(node_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _entry_exists(entry: dict[str, Any]) -> bool:
    path = _resolve_media_file(
        entry.get("type", "output"),
        entry.get("subfolder", ""),
        entry.get("filename", ""),
    )
    return bool(path and path.is_file() and path.stat().st_size > 0)


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": os.path.basename(str(entry.get("filename", ""))),
        "subfolder": _safe_subfolder(entry.get("subfolder", "")),
        "type": str(entry.get("type", "output") or "output"),
        "thumb_filename": os.path.basename(str(entry.get("thumb_filename", ""))),
        "thumb_subfolder": _safe_subfolder(entry.get("thumb_subfolder", "")),
        "thumb_type": str(entry.get("thumb_type", entry.get("type", "output")) or "output"),
        "preview_filename": os.path.basename(str(entry.get("preview_filename", ""))),
        "preview_subfolder": _safe_subfolder(entry.get("preview_subfolder", "")),
        "preview_type": str(entry.get("preview_type", "output") or "output"),
        "timestamp": float(entry.get("timestamp", 0.0) or 0.0),
        "frame_rate": float(entry.get("frame_rate", 0.0) or 0.0),
        "format": str(entry.get("format", "") or ""),
        "bit_depth": str(entry.get("bit_depth", "Auto (format)") or "Auto (format)"),
        "actual_bit_depth": str(entry.get("actual_bit_depth", "") or ""),
        "width": int(entry.get("width", 0) or 0),
        "height": int(entry.get("height", 0) or 0),
        "duration": float(entry.get("duration", 0.0) or 0.0),
        "frame_count": int(entry.get("frame_count", 0) or 0),
        "codec": str(entry.get("codec", "") or ""),
        "pixel_format": str(entry.get("pixel_format", "") or ""),
        "is_image": bool(entry.get("is_image", False)),
        "fullpath": str(entry.get("fullpath", "") or ""),
        "workflow_filename": os.path.basename(str(entry.get("workflow_filename", "") or "")),
        "workflow_subfolder": _safe_subfolder(entry.get("workflow_subfolder", "")),
        "workflow_type": str(entry.get("workflow_type", entry.get("type", "output")) or "output"),
    }


def _get_history(node_id: Any, limit: int = _HISTORY_LIMIT) -> list[dict[str, Any]]:
    data = _load_manifest(node_id)
    entries = [entry for entry in data.get("entries", []) if isinstance(entry, dict) and _entry_exists(entry)]
    entries.sort(key=lambda item: float(item.get("timestamp", 0.0) or 0.0), reverse=True)
    trimmed = entries[:_MAX_MANIFEST_ENTRIES]
    if trimmed != data.get("entries", []):
        data["entries"] = trimmed
        try:
            _save_manifest(node_id, data)
        except Exception:
            pass
    return [_public_entry(entry) for entry in trimmed[: max(1, int(limit))]]


def _append_history(node_id: Any, entry: dict[str, Any]) -> None:
    data = _load_manifest(node_id)
    entries = [item for item in data.get("entries", []) if isinstance(item, dict)]
    key = (
        str(entry.get("type", "output")),
        _safe_subfolder(entry.get("subfolder", "")),
        os.path.basename(str(entry.get("filename", ""))),
    )
    kept: list[dict[str, Any]] = []
    for item in entries:
        item_key = (
            str(item.get("type", "output")),
            _safe_subfolder(item.get("subfolder", "")),
            os.path.basename(str(item.get("filename", ""))),
        )
        if item_key != key:
            kept.append(item)
    data["entries"] = [entry, *kept][:_MAX_MANIFEST_ENTRIES]
    _save_manifest(node_id, data)


def _resolve_vhs_video_combine():
    # Preserve the workflow ABI while resolving the pack's own encoder.
    from .video_engine.encoder import VideoCombine
    return VideoCombine


def _copy_vhs_input_types() -> dict[str, Any]:
    cls = _resolve_vhs_video_combine()
    data = cls.INPUT_TYPES()
    # Avoid mutating Video Combine's own schema. Keep the custom ContainsAll hidden
    # mapping object untouched because it is intentionally permissive for format widgets.
    result: dict[str, Any] = dict(data)
    required = dict(data.get("required", {}))
    rebuilt: dict[str, Any] = {}
    inserted = False
    for key, value in required.items():
        # Reuse the installed node's schema object exactly; Lyonir only inserts one widget.
        rebuilt[key] = value
        if key == "format":
            rebuilt["bit_depth"] = (
                "COMBO",
                {
                    "options": list(_BIT_DEPTHS),
                    "default": "Auto (format)",
                    "tooltip": (
                        "Output bit depth. Auto keeps the exact Video Combine preset. "
                        "When a fixed depth is selected, Lyonir selects a compatible pix_fmt from that same preset. "
                        "This input is a real COMBO socket, so it can also accept bit_depth directly from Get Video Components."
                    ),
                },
            )
            inserted = True
    if not inserted:
        rebuilt["bit_depth"] = (
            "COMBO",
            {"options": list(_BIT_DEPTHS), "default": "Auto (format)"},
        )
    result["required"] = rebuilt
    result["optional"] = dict(data.get("optional", {}))
    # Preserve the exact hidden mapping object used by Video Combine when possible.
    if "hidden" in data:
        result["hidden"] = data["hidden"]
    return result


def _fallback_input_types() -> dict[str, Any]:
    return {
        "required": {
            "images": ("IMAGE",),
            "frame_rate": ("FLOAT", {"default": 8.0, "min": 1.0, "step": 1.0}),
            "loop_count": ("INT", {"default": 0, "min": 0, "max": 100, "step": 1}),
            "filename_prefix": ("STRING", {"default": "AnimateDiff"}),
            "format": (["video/h264-mp4"],),
            "bit_depth": (
                "COMBO",
                {"options": list(_BIT_DEPTHS), "default": "Auto (format)"},
            ),
            "pingpong": ("BOOLEAN", {"default": False}),
            "save_output": ("BOOLEAN", {"default": True}),
        },
        "optional": {
            "audio": ("AUDIO",),
            "meta_batch": ("VHS_BatchManager",),
            "vae": ("VAE",),
        },
        "hidden": {
            "prompt": "PROMPT",
            "extra_pnginfo": "EXTRA_PNGINFO",
            "unique_id": "UNIQUE_ID",
        },
    }


def _format_widget_defs(vhs_cls, format_name: str) -> list[Any]:
    try:
        input_types = vhs_cls.INPUT_TYPES()
        spec = input_types.get("required", {}).get("format")
        metadata = spec[1] if isinstance(spec, (list, tuple)) and len(spec) > 1 and isinstance(spec[1], dict) else {}
        formats = metadata.get("formats", {}) if isinstance(metadata, dict) else {}
        defs = formats.get(format_name, []) if isinstance(formats, dict) else []
        return defs if isinstance(defs, list) else []
    except Exception:
        return []


def _widget_default(widget_def: Any) -> Any:
    if not isinstance(widget_def, (list, tuple)) or len(widget_def) < 2:
        return None
    kind = widget_def[1]
    options = widget_def[2] if len(widget_def) > 2 and isinstance(widget_def[2], dict) else {}
    if "default" in options:
        return options["default"]
    if isinstance(kind, (list, tuple)) and kind:
        return kind[0]
    return None


def _pix_fmt_depth(pix_fmt: Any) -> int:
    text = str(pix_fmt or "").lower()
    if not text:
        return 0
    if "16" in text:
        return 16
    if "14" in text:
        return 14
    if "12" in text or text.startswith("p012"):
        return 12
    if "10" in text or text.startswith("p010"):
        return 10
    return 8


def _requested_depth(bit_depth: str) -> int | None:
    if str(bit_depth or "").startswith("Auto"):
        return None
    match = re.search(r"(8|10|12|16)", str(bit_depth))
    return int(match.group(1)) if match else None


def _pix_signature(pix_fmt: Any) -> tuple[str, bool]:
    text = str(pix_fmt or "").lower()
    alpha = text.startswith("yuva") or text.startswith("rgba") or text.startswith("bgra") or "a" in text.split("p")[0]
    if "420" in text or text.startswith(("p010", "p012")):
        chroma = "420"
    elif "422" in text:
        chroma = "422"
    elif "444" in text:
        chroma = "444"
    elif text.startswith(("rgb", "bgr", "gbr")):
        chroma = "rgb"
    else:
        chroma = ""
    return chroma, alpha


def _choose_pix_fmt(options: list[Any], current: Any, depth: int) -> str | None:
    candidates = [str(value) for value in options if _pix_fmt_depth(value) == depth]
    if not candidates:
        return None
    current_chroma, current_alpha = _pix_signature(current)

    def score(value: str) -> tuple[int, int, int]:
        chroma, alpha = _pix_signature(value)
        return (
            1 if alpha == current_alpha else 0,
            1 if current_chroma and chroma == current_chroma else 0,
            1 if str(value) == str(current) else 0,
        )

    return max(candidates, key=score)


def _arg_value(args: Any, names: tuple[str, ...]) -> str:
    if not isinstance(args, (list, tuple)):
        return ""
    flat = [str(x) for x in args if not isinstance(x, (list, tuple, dict))]
    for index, value in enumerate(flat):
        if value in names and index + 1 < len(flat):
            return flat[index + 1]
    return ""


def _finalized_format_data(vhs_cls, format_name: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    if not str(format_name).startswith("video/"):
        return None
    try:
        module = importlib.import_module(vhs_cls.__module__)
        apply_format_widgets = getattr(module, "apply_format_widgets", None)
        if not callable(apply_format_widgets):
            return None
        return apply_format_widgets(str(format_name).split("/", 1)[1], dict(kwargs))
    except Exception:
        return None


def _apply_bit_depth(vhs_cls, format_name: str, bit_depth: str, kwargs: dict[str, Any]) -> tuple[dict[str, Any], str]:
    requested = _requested_depth(bit_depth)
    if requested is None or not str(format_name).startswith("video/"):
        return kwargs, str(kwargs.get("pix_fmt", "") or "")

    defs = _format_widget_defs(vhs_cls, format_name)
    pix_def = next((item for item in defs if isinstance(item, (list, tuple)) and item and item[0] == "pix_fmt"), None)
    if pix_def is not None:
        kind = pix_def[1] if len(pix_def) > 1 else None
        current = kwargs.get("pix_fmt", _widget_default(pix_def))
        if isinstance(kind, (list, tuple)):
            chosen = _choose_pix_fmt(list(kind), current, requested)
            if chosen is None:
                available = sorted({_pix_fmt_depth(v) for v in kind if _pix_fmt_depth(v)})
                readable = ", ".join(f"{depth}-bit" for depth in available) or "the preset default only"
                raise ValueError(
                    f"{format_name} does not expose a {requested}-bit pixel format in Video Combine. "
                    f"Available for this preset: {readable}. Choose a compatible bit depth or Auto (format)."
                )
            updated = dict(kwargs)
            updated["pix_fmt"] = chosen
            return updated, chosen

    finalized = _finalized_format_data(vhs_cls, format_name, kwargs)
    if finalized:
        fixed_pix = str(finalized.get("pix_fmt", "") or "")
        if not fixed_pix:
            fixed_pix = _arg_value(finalized.get("main_pass", []), ("-pix_fmt",))
        if fixed_pix:
            actual = _pix_fmt_depth(fixed_pix)
            if actual != requested:
                raise ValueError(
                    f"{format_name} is fixed to {fixed_pix} ({actual}-bit) by the Video Combine preset. "
                    f"It cannot be safely forced to {requested}-bit. Use Auto (format), {actual}-bit, or another format."
                )
            return kwargs, fixed_pix

    # Some Video Combine presets (notably ProRes presets in several VHS builds)
    # intentionally hide pix_fmt and let the preset/encoder choose the correct
    # internal pixel format. Do not fail the entire generation in that case.
    # We preserve the preset exactly and verify the actual saved pixel format
    # afterwards with ffprobe whenever it is available.
    print(
        f"[Lyonir Save Video] {format_name} does not expose a controllable pix_fmt; "
        f"delegating the requested {requested}-bit output to the Video Combine preset."
    )
    return kwargs, ""


def _cpu_audio(audio: Any) -> Any:
    # VideoHelperSuite currently converts AUDIO to numpy during muxing. Keeping the
    # waveform on CPU avoids the known --gpu-only failure without changing audio data.
    if not isinstance(audio, dict):
        return audio
    waveform = audio.get("waveform")
    if waveform is None or not hasattr(waveform, "to"):
        return audio
    try:
        if getattr(waveform, "device", None) is not None and str(waveform.device) != "cpu":
            cloned = dict(audio)
            cloned["waveform"] = waveform.detach().to(device="cpu")
            return cloned
    except Exception:
        pass
    return audio


def _find_ffmpeg(vhs_cls=None) -> str | None:
    if vhs_cls is not None:
        try:
            module = importlib.import_module(vhs_cls.__module__)
            candidate = getattr(module, "ffmpeg_path", None)
            if candidate and os.path.isfile(candidate):
                return str(candidate)
        except Exception:
            pass
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg  # type: ignore
        candidate = imageio_ffmpeg.get_ffmpeg_exe()
        if candidate and os.path.isfile(candidate):
            return candidate
    except Exception:
        pass
    return None


def _find_ffprobe(ffmpeg: str | None) -> str | None:
    system = shutil.which("ffprobe")
    if system:
        return system
    if ffmpeg:
        path = Path(ffmpeg)
        sibling = path.with_name("ffprobe.exe" if path.suffix.lower() == ".exe" else "ffprobe")
        if sibling.is_file():
            return str(sibling)
    return None


def _probe_media(path: Path, ffmpeg: str | None) -> dict[str, Any]:
    ffprobe = _find_ffprobe(ffmpeg)
    if not ffprobe:
        if not ffmpeg:
            return {}
        # The bundled FFmpeg can inspect streams without a separate ffprobe.
        try:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path), "-map", "0:v:0", "-frames:v", "0", "-f", "null", "-"],
                capture_output=True, text=True, timeout=15,
            )
            text = result.stderr or ""
            stream = next((line for line in text.splitlines() if "Stream #0:" in line and "Video:" in line), "")
            match = re.search(r"Video:\s*([^,\s]+).*?,\s*([a-z][a-z0-9]+)(?:\([^)]*\))?,\s*(\d+)x(\d+)", stream)
            duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
            if not match:
                return {}
            seconds = (int(duration[1])*3600 + int(duration[2])*60 + float(duration[3])) if duration else 0.0
            return {"codec": match[1], "pixel_format": match[2], "width": int(match[3]), "height": int(match[4]), "duration": seconds, "frame_count": 0}
        except Exception:
            return {}
    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,pix_fmt,width,height,bits_per_raw_sample,nb_frames:format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0] or {}
        fmt = data.get("format") or {}
        nb_frames = stream.get("nb_frames", 0)
        try:
            frame_count = int(nb_frames or 0)
        except Exception:
            frame_count = 0
        return {
            "codec": str(stream.get("codec_name", "") or ""),
            "pixel_format": str(stream.get("pix_fmt", "") or ""),
            "bits_per_raw_sample": int(stream.get("bits_per_raw_sample", 0) or 0) if str(stream.get("bits_per_raw_sample", "") or "").isdigit() else 0,
            "width": int(stream.get("width", 0) or 0),
            "height": int(stream.get("height", 0) or 0),
            "duration": float(fmt.get("duration", 0.0) or 0.0),
            "frame_count": frame_count,
        }
    except Exception:
        return {}


def _thumbnail_from_workflow(preview: dict[str, Any]) -> tuple[str, str, str] | None:
    workflow = os.path.basename(str(preview.get("workflow", "") or ""))
    if not workflow:
        return None
    media_type = str(preview.get("type", "output") or "output")
    subfolder = _safe_subfolder(preview.get("subfolder", ""))
    path = _resolve_media_file(media_type, subfolder, workflow)
    if path and path.is_file():
        return workflow, subfolder, media_type
    return None


def _extract_thumbnail(ffmpeg: str | None, master_path: Path, node_id: Any) -> tuple[str, str, str] | None:
    if not ffmpeg:
        return None
    subfolder = f"{_HISTORY_DIRNAME}/{_THUMB_DIRNAME}/node_{_safe_node_id(node_id)}"
    folder = Path(folder_paths.get_output_directory()) / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{master_path.stem}.jpg"
    target = folder / filename
    cmd = [ffmpeg, "-v", "error", "-y", "-i", str(master_path), "-frames:v", "1", "-q:v", "3", str(target)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and target.is_file():
            return filename, subfolder, "output"
    except Exception:
        pass
    return None


def _browser_preview_proxy(
    ffmpeg: str | None,
    master_path: Path,
    node_id: Any,
    format_name: str,
) -> tuple[str, str, str] | None:
    if not ffmpeg or not str(format_name).startswith("video/"):
        return None
    ext = master_path.suffix.lower()
    # Common browser-native masters do not need a second file.
    browser_safe = (
        str(format_name) == "video/h264-mp4"
        or ext == ".webm"
    )
    if browser_safe:
        return None

    subfolder = f"{_HISTORY_DIRNAME}/{_PREVIEW_DIRNAME}/node_{_safe_node_id(node_id)}"
    folder = Path(folder_paths.get_output_directory()) / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{master_path.stem}_preview.mp4"
    target = folder / filename
    cmd = [
        ffmpeg, "-v", "error", "-y", "-i", str(master_path),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(target),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0 and target.is_file():
            return filename, subfolder, "output"
    except Exception:
        pass
    return None


def _preview_from_response(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    ui = response.get("ui")
    if not isinstance(ui, dict):
        return None
    gifs = ui.get("gifs")
    if isinstance(gifs, list) and gifs and isinstance(gifs[0], dict):
        return dict(gifs[0])
    return None


def _result_files(response: Any) -> tuple[bool, list[str]]:
    if not isinstance(response, dict):
        return True, []
    result = response.get("result")
    if not isinstance(result, tuple) or not result:
        return True, []
    filenames = result[0]
    if not isinstance(filenames, tuple) or len(filenames) < 2:
        return True, []
    save_output = bool(filenames[0])
    files = filenames[1] if isinstance(filenames[1], list) else []
    return save_output, [str(path) for path in files]


def _entry_from_success(
    response: dict[str, Any],
    node_id: Any,
    bit_depth: str,
    format_name: str,
    frame_rate: Any,
    vhs_cls,
) -> dict[str, Any] | None:
    preview = _preview_from_response(response) or {}
    save_output, files = _result_files(response)
    if not files and not preview.get("filename"):
        return None

    media_type = str(preview.get("type", "output" if save_output else "temp") or ("output" if save_output else "temp"))
    subfolder = _safe_subfolder(preview.get("subfolder", ""))
    filename = os.path.basename(str(preview.get("filename", "") or ""))

    master_path: Path | None = None
    fullpath = str(preview.get("fullpath", "") or "")
    # FFmpeg image-sequence outputs return a filename pattern, not a file.
    # Keep the original sequence on disk and use its first frame in the gallery.
    if "%03d" in fullpath and str(format_name).endswith("bit-png"):
        first_frame = Path(fullpath.replace("%03d", "001"))
        if first_frame.is_file():
            fullpath = str(first_frame)
            filename = first_frame.name
            format_name = "image/png"
    if fullpath:
        candidate = Path(fullpath)
        if candidate.is_file():
            master_path = candidate
    if master_path is None and files:
        candidate = Path(files[-1])
        if candidate.is_file():
            master_path = candidate
    if master_path is None and filename:
        master_path = _resolve_media_file(media_type, subfolder, filename)

    if master_path is None or not master_path.is_file() or master_path.stat().st_size <= 0:
        raise RuntimeError("Video Combine returned success, but the final saved media file could not be verified on disk.")

    if not filename:
        filename = master_path.name
    if not subfolder:
        try:
            root = _root_for_type(media_type).resolve()
            subfolder = _safe_subfolder(str(master_path.resolve().parent.relative_to(root)))
        except Exception:
            subfolder = ""

    is_image = str(format_name).startswith("image/")
    ffmpeg = _find_ffmpeg(vhs_cls)
    probe = {} if is_image else _probe_media(master_path, ffmpeg)

    thumb = _thumbnail_from_workflow(preview)
    if thumb is None and is_image:
        thumb = (filename, subfolder, media_type)
    if thumb is None:
        thumb = _extract_thumbnail(ffmpeg, master_path, node_id)

    proxy = None if is_image else _browser_preview_proxy(ffmpeg, master_path, node_id, format_name)

    workflow_filename = os.path.basename(str(preview.get("workflow", "") or ""))
    workflow_path = _resolve_media_file(media_type, subfolder, workflow_filename) if workflow_filename else None
    if not workflow_path or not workflow_path.is_file():
        workflow_filename = ""

    probed_frame_count = int(probe.get("frame_count", 0) or 0)
    if not probed_frame_count and probe.get("duration") and frame_rate:
        try:
            probed_frame_count = max(0, int(round(float(probe.get("duration", 0.0)) * float(frame_rate))))
        except Exception:
            probed_frame_count = 0

    actual_depth = _pix_fmt_depth(str(probe.get("pixel_format", "") or ""))
    if not actual_depth:
        try:
            raw_depth = int(probe.get("bits_per_raw_sample", 0) or 0)
            actual_depth = raw_depth if raw_depth in (8, 10, 12, 16) else None
        except Exception:
            actual_depth = None

    entry = {
        "filename": filename,
        "subfolder": subfolder,
        "type": media_type,
        "fullpath": str(master_path),
        "workflow_filename": workflow_filename,
        "workflow_subfolder": subfolder if workflow_filename else "",
        "workflow_type": media_type,
        "thumb_filename": thumb[0] if thumb else "",
        "thumb_subfolder": thumb[1] if thumb else "",
        "thumb_type": thumb[2] if thumb else media_type,
        "preview_filename": proxy[0] if proxy else "",
        "preview_subfolder": proxy[1] if proxy else "",
        "preview_type": proxy[2] if proxy else "output",
        "timestamp": time.time(),
        "frame_rate": float(preview.get("frame_rate", frame_rate) or 0.0),
        "format": str(format_name),
        "bit_depth": str(bit_depth),
        "actual_bit_depth": f"{actual_depth}-bit" if actual_depth else "",
        "width": int(probe.get("width", 0) or 0),
        "height": int(probe.get("height", 0) or 0),
        "duration": float(probe.get("duration", 0.0) or 0.0),
        "frame_count": probed_frame_count,
        "codec": str(probe.get("codec", "") or ""),
        "pixel_format": str(probe.get("pixel_format", "") or ""),
        "is_image": is_image,
    }
    return entry


def _history_id_from_workflow(extra_pnginfo: Any, unique_id: Any) -> str:
    """Read the persistent Lyonir gallery UUID from the node's serialized properties.

    The identifier intentionally lives in workflow node.properties instead of an
    input widget, so it is persisted across reloads without appearing in the UI.
    """
    try:
        payload = extra_pnginfo if isinstance(extra_pnginfo, dict) else {}
        workflow = payload.get("workflow") if isinstance(payload, dict) else None
        if not isinstance(workflow, dict):
            return ""
        nodes = workflow.get("nodes")
        if not isinstance(nodes, list):
            return ""
        target = str(unique_id)
        for node in nodes:
            if not isinstance(node, dict) or str(node.get("id")) != target:
                continue
            properties = node.get("properties")
            if isinstance(properties, dict):
                value = str(properties.get("lyonir_history_id") or "").strip()
                if value:
                    return value
    except Exception:
        pass
    return ""


class LyonirSaveVideo:
    """VHS Video Combine behavior plus explicit bit-depth selection and persistent visual history."""

    @classmethod
    def INPUT_TYPES(cls):
        try:
            return _copy_vhs_input_types()
        except Exception:
            # Keep the pack loadable even when Video Combine is temporarily disabled.
            return _fallback_input_types()

    RETURN_TYPES = ("VHS_FILENAMES",)
    RETURN_NAMES = ("Filenames",)
    OUTPUT_NODE = True
    CATEGORY = "Lyonir Studio/Video"
    FUNCTION = "combine_video"
    DESCRIPTION = (
        "Video Combine-compatible output node with persistent Lyonir history. Encoding is performed by "
        "the internal VideoCombine-compatible encoder so formats, format-specific widgets, naming, audio, metadata, ping-pong, "
        "Meta Batch, VAE and save behavior stay aligned with Video Combine. The frontend mirrors the VHS preview "
        "and native node context menu, while adding selectable previous outputs and explicit bit-depth selection."
    )

    def combine_video(
        self,
        frame_rate: Any,
        loop_count: int,
        images=None,
        latents=None,
        filename_prefix="AnimateDiff",
        format="image/gif",
        bit_depth="Auto (format)",
        pingpong=False,
        save_output=True,
        prompt=None,
        extra_pnginfo=None,
        audio=None,
        unique_id=None,
        manual_format_widgets=None,
        meta_batch=None,
        vae=None,
        **kwargs,
    ):
        vhs_cls = _resolve_vhs_video_combine()
        adjusted_kwargs, _ = _apply_bit_depth(vhs_cls, str(format), str(bit_depth), dict(kwargs))

        call_kwargs = dict(adjusted_kwargs)
        call_kwargs.update(
            {
                "frame_rate": frame_rate,
                "loop_count": loop_count,
                "images": images,
                "latents": latents,
                "filename_prefix": filename_prefix,
                "format": format,
                "pingpong": pingpong,
                "save_output": save_output,
                "prompt": prompt,
                "extra_pnginfo": extra_pnginfo,
                "audio": _cpu_audio(audio),
                "unique_id": unique_id,
                "manual_format_widgets": manual_format_widgets,
                "meta_batch": meta_batch,
                "vae": vae,
            }
        )

        delegate = vhs_cls()
        combine_method = delegate.combine_video

        # Most VHS builds accept **kwargs for format-specific widgets. A few forks
        # expose a stricter signature; preserve compatibility without leaking
        # Lyonir-only values into those implementations. If the fork exposes the
        # legacy manual_format_widgets input, route extra format values through it.
        try:
            signature = inspect.signature(combine_method)
            parameters = signature.parameters
            accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
        except Exception:
            parameters = {}
            accepts_kwargs = True

        if accepts_kwargs:
            response = combine_method(**call_kwargs)
        else:
            allowed = set(parameters)
            filtered = {key: value for key, value in call_kwargs.items() if key in allowed}
            extras = {key: value for key, value in adjusted_kwargs.items() if key not in allowed}
            if extras and "manual_format_widgets" in allowed:
                manual = filtered.get("manual_format_widgets")
                merged = dict(manual) if isinstance(manual, dict) else {}
                merged.update(extras)
                filtered["manual_format_widgets"] = merged
            response = combine_method(**filtered)

        # Older implementations may return the result tuple directly. Preserve it
        # exactly; history requires the modern UI preview/result dictionary.
        if not isinstance(response, dict):
            return response

        ui = response.get("ui") if isinstance(response.get("ui"), dict) else {}
        if ui.get("unfinished_batch"):
            return response

        # History is keyed by a persistent UUID stored invisibly in the node's
        # workflow properties. The UUID is not an input widget, so it never appears
        # on the node surface. Legacy workflows fall back to the numeric id only
        # until the frontend saves them once with the new property.
        history_key = _history_id_from_workflow(extra_pnginfo, unique_id) or str(unique_id or "unknown")

        entry = _entry_from_success(
            response=response,
            node_id=history_key,
            bit_depth=str(bit_depth),
            format_name=str(format),
            frame_rate=frame_rate,
            vhs_cls=vhs_cls,
        )
        if entry is not None:
            requested_depth = _requested_depth(str(bit_depth))
            actual_depth = _requested_depth(str(entry.get("actual_bit_depth", "")))
            if requested_depth is not None and actual_depth is not None:
                if requested_depth == actual_depth:
                    print(
                        f"[Lyonir Save Video] Verified saved output: requested {requested_depth}-bit, "
                        f"actual pixel format {entry.get('pixel_format', '')} ({actual_depth}-bit)."
                    )
                else:
                    print(
                        f"[Lyonir Save Video] WARNING: requested {requested_depth}-bit, but the preset saved "
                        f"{entry.get('pixel_format', 'an unknown pixel format')} ({actual_depth}-bit). "
                        "The file was kept because encoding completed successfully; choose Auto (format) or a preset "
                        "with an exposed pix_fmt if exact bit-depth enforcement is required."
                    )
            try:
                _append_history(history_key, entry)
                history = _get_history(history_key, _HISTORY_LIMIT)
            except Exception as exc:
                print(f"[Lyonir Save Video] history warning: {exc}")
                history = [_public_entry(entry)]
            ui = dict(ui)
            ui["lyonir_video_gallery_current"] = [_public_entry(entry)]
            ui["lyonir_video_gallery_history"] = history
            ui["lyonir_video_gallery_history_id"] = [history_key]
            response = dict(response)
            response["ui"] = ui
        return response

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        # Dynamic format widgets are supplied by the Video Combine preset metadata.
        # Accept them here exactly as VHS_VideoCombine does.
        return True


@PromptServer.instance.routes.get("/lyonir/save-video/history")
async def lyonir_save_video_history(request):
    # v3.5.13+: history_id is a persistent UUID stored invisibly in node properties. node_id is
    # accepted only as a compatibility fallback for callers from older frontends.
    history_id = request.query.get("history_id") or request.query.get("node_id", "unknown")
    try:
        limit = int(request.query.get("limit", str(_HISTORY_LIMIT)))
    except Exception:
        limit = _HISTORY_LIMIT
    try:
        return web.json_response({"ok": True, "history": _get_history(history_id, max(1, min(100, limit)))})
    except Exception as exc:
        return web.json_response({"ok": False, "history": [], "error": str(exc)}, status=500)


@PromptServer.instance.routes.get("/lyonir/save-video/media")
async def lyonir_save_video_media(request):
    media_type = request.query.get("type", "output")
    subfolder = request.query.get("subfolder", "")
    filename = request.query.get("filename", "")
    path = _resolve_media_file(media_type, subfolder, filename)
    if path is None or not path.is_file():
        raise web.HTTPNotFound(text="Lyonir video media not found")
    return web.FileResponse(path)
