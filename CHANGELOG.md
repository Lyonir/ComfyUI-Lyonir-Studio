# v3.5.18

- Save Image displays selected image generation seed and actual resolution above the clean preview.
- Copiar seed copies the selected generation seed with exact 64-bit precision.
- Each Save Image node has a persistent independent gallery identity; cloned nodes receive a fresh identity.
- Legacy shared histories are not imported; existing image files remain saved.

# v3.5.17

- Save Video records upstream generation seeds in per-video history.
- Selected video seed and real resolution appear below save_output without covering the preview.
- Copiar seed copies the selected seed without losing 64-bit digits and confirms success.
- Existing history without recorded seeds remains usable and displays Unavailable.

# v3.5.16

Lyonir Sampler now reports one monotonic total progress across sampling, video decoding, cropping and audio decoding. Native preview images are preserved. No sampling parameters or output processing changed.

# v3.5.15
- Internal VideoCombine-compatible video encoder; external VHS installation no longer required for Save Video.
- Windows x64 FFmpeg bundled inside the node folder; no automatic pip or global configuration changes.
- Preserve workflow ABI, format presets, audio, batching, VAE input and frontend galleries.
- PNG sequence gallery fix and bundled-FFmpeg output inspection fallback.
- GPL-3.0 combined distribution with retained upstream notices.

# Changelog

## v3.5.14

- Add 🐺 Lyonir Model Family to share a family selection with Resolution and Sampler.
- Preserve existing node IDs, dropdowns and workflow behavior.

## v3.5.13

Initial public GitHub release baseline.

- Lyonir Save Video with VideoHelperSuite encoding parity and persistent per-node history.
- Hidden history UUID.
- Proportional preview/node resizing.
- Adjustable thumbnail-size slider.
- Hover-based preview audio and bidirectional Sync Preview compatibility.
- Dynamic Video Combine widgets restored correctly after workflow reload.
- ProRes bit-depth fallback behavior.
- Lyonir Save Image persistent gallery.
- Lyonir Image Compare.
- Lyonir Resolution.
- Multi-model Lyonir Sampler.
- Qwen3-TTS nodes.
