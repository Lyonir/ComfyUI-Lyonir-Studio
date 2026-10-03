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
