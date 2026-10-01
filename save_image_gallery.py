from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import folder_paths
from aiohttp import web
from nodes import SaveImage
from server import PromptServer


_HISTORY_DIRNAME = ".lyonir_gallery"
_MANIFEST_VERSION = 1
_MAX_MANIFEST_ENTRIES = 1000


def _safe_node_id(value: Any) -> str:
    text = str(value if value is not None else "unknown")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return text or "unknown"


def _safe_subfolder(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    text = text.strip("/")
    if not text:
        return ""
    parts = []
    for part in text.split("/"):
        part = part.strip()
        if not part or part in {".", ".."}:
            continue
        part = re.sub(r"[<>:\"|?*]+", "_", part)
        parts.append(part)
    return "/".join(parts)


def _safe_prefix(value: Any) -> str:
    text = str(value or "Lyonir").strip().replace("\\", "_").replace("/", "_")
    text = re.sub(r"[<>:\"|?*]+", "_", text)
    return text or "Lyonir"


def _history_dir() -> Path:
    root = Path(folder_paths.get_output_directory())
    path = root / _HISTORY_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path(node_id: Any) -> Path:
    return _history_dir() / f"node_{_safe_node_id(node_id)}.json"


def _load_manifest(node_id: Any) -> dict[str, Any]:
    path = _manifest_path(node_id)
    if not path.exists():
        return {"version": _MANIFEST_VERSION, "node_id": str(node_id), "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("manifest root must be an object")
        entries = data.get("entries")
        if not isinstance(entries, list):
            entries = []
        return {
            "version": int(data.get("version", _MANIFEST_VERSION)),
            "node_id": str(data.get("node_id", node_id)),
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
    if entry.get("type", "output") != "output":
        return False
    root = Path(folder_paths.get_output_directory()).resolve()
    subfolder = _safe_subfolder(entry.get("subfolder", ""))
    filename = os.path.basename(str(entry.get("filename", "")))
    if not filename:
        return False
    candidate = (root / subfolder / filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate.is_file()


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": os.path.basename(str(entry.get("filename", ""))),
        "subfolder": _safe_subfolder(entry.get("subfolder", "")),
        "type": "output",
        "timestamp": float(entry.get("timestamp", 0.0) or 0.0),
    }


def _get_history(node_id: Any, limit: int = 24) -> list[dict[str, Any]]:
    data = _load_manifest(node_id)
    valid = [entry for entry in data.get("entries", []) if isinstance(entry, dict) and _entry_exists(entry)]
    valid.sort(key=lambda item: float(item.get("timestamp", 0.0) or 0.0), reverse=True)

    # Keep the manifest healthy if files were moved/deleted outside ComfyUI.
    trimmed_for_manifest = valid[:_MAX_MANIFEST_ENTRIES]
    if trimmed_for_manifest != data.get("entries", []):
        data["entries"] = trimmed_for_manifest
        try:
            _save_manifest(node_id, data)
        except Exception:
            pass

    limit = max(1, min(int(limit), 100))
    return [_public_entry(entry) for entry in valid[:limit]]


def _append_history(node_id: Any, saved_images: list[dict[str, Any]]) -> None:
    data = _load_manifest(node_id)
    entries = [entry for entry in data.get("entries", []) if isinstance(entry, dict)]
    now = time.time()
    for index, info in enumerate(saved_images):
        entries.append(
            {
                "filename": os.path.basename(str(info.get("filename", ""))),
                "subfolder": _safe_subfolder(info.get("subfolder", "")),
                "type": "output",
                "timestamp": now + index * 0.000001,
            }
        )
    entries.sort(key=lambda item: float(item.get("timestamp", 0.0) or 0.0), reverse=True)
    data["version"] = _MANIFEST_VERSION
    data["node_id"] = str(node_id)
    data["entries"] = entries[:_MAX_MANIFEST_ENTRIES]
    _save_manifest(node_id, data)


class LyonirSaveImage(SaveImage):
    """Save images and expose a persistent, clickable history in the node UI."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Image or image batch to save."}),
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "Lyonir",
                        "tooltip": "Filename prefix for saved images.",
                    },
                ),
                "subfolder": (
                    "STRING",
                    {
                        "default": "Lyonir",
                        "tooltip": "Subfolder inside ComfyUI/output used by this gallery.",
                    },
                ),
                "history_limit": (
                    "INT",
                    {
                        "default": 18,
                        "min": 4,
                        "max": 100,
                        "step": 1,
                        "tooltip": "Maximum number of recent thumbnails shown in the node.",
                    },
                ),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "save_with_history"
    CATEGORY = "Lyonir Studio/Image"
    OUTPUT_NODE = True
    DESCRIPTION = (
        "Saves images to ComfyUI/output and keeps a persistent clickable thumbnail history "
        "inside the node. The IMAGE output is a passthrough of the current input."
    )

    def save_with_history(
        self,
        image,
        filename_prefix="Lyonir",
        subfolder="Lyonir",
        history_limit=18,
        prompt=None,
        extra_pnginfo=None,
        unique_id=None,
    ):
        safe_prefix = _safe_prefix(filename_prefix)
        safe_subfolder = _safe_subfolder(subfolder)
        combined_prefix = f"{safe_subfolder}/{safe_prefix}" if safe_subfolder else safe_prefix

        saved = super().save_images(
            image,
            filename_prefix=combined_prefix,
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
        )
        saved_images = list(saved.get("ui", {}).get("images", []))

        try:
            _append_history(unique_id, saved_images)
            history = _get_history(unique_id, history_limit)
        except Exception as exc:
            # Saving the image is the critical operation. A gallery bookkeeping
            # failure must never throw away a successful render.
            print(f"[Lyonir Save Image] history warning: {exc}")
            history = [_public_entry(item) for item in reversed(saved_images)]

        return {
            "ui": {
                "lyonir_gallery_current": saved_images,
                "lyonir_gallery_history": history,
                "lyonir_gallery_node_id": [str(unique_id)],
            },
            "result": (image,),
        }


@PromptServer.instance.routes.get("/lyonir/save-image/history")
async def lyonir_save_image_history(request):
    node_id = request.query.get("node_id", "unknown")
    try:
        limit = int(request.query.get("limit", "18"))
    except Exception:
        limit = 18
    try:
        history = _get_history(node_id, limit)
        return web.json_response({"ok": True, "history": history})
    except Exception as exc:
        return web.json_response({"ok": False, "history": [], "error": str(exc)}, status=500)
