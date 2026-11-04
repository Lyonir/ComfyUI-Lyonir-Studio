# v3.5.31

- Fix LTX 1280x720 -> 1280x704 regression caused by re-encoding a 720px image into a 32x-compressed latent in v3.5.30.
- REMOVE the v3.5.30 VAE encode/re-encode step. LATENT returns the original sampled tensor, preserving quality for a second sampling stage.
- The LATENT carries exact final crop metadata; bundled hooks post-crop stock **VAEDecode** and **VAEDecodeTiled** images without an extra workflow node, preserving exact requested pixels even when LATENT passes through LTX AV split/concat.
- IMAGE remains hard-cropped immediately in Lyonir Sampler. Sampling behavior stays based on v3.5.24.
- Basic Scheduler/Manual Sigmas UI and Ctrl+C/Ctrl+V fixes remain from v3.5.29.
- Note: native LTX latent grids cannot *physically* represent arbitrary pixel dimensions; exact 720px is enforced after VAE decoding. Other third-party decoders not patched here cannot be promised the exact crop.
- No changes to other nodes.

# v3.5.29 (local test build; not published)

- Fix the Lyonir Sampler Manual Sigmas input position in current Vue-based ComfyUI: use a registered `converted-widget` row *immediately below Sampling Mode*. Non-widget inputs are always drawn at the top in Vue; overriding `slot.pos` alone could not move the actual row.
- Preserve an actual `SIGMAS` connector, displayed only in Manual Sigmas mode; Basic Scheduler keeps steps/scheduler/denoise below Sampling Mode.
- Keep Ctrl+C/Ctrl+V and workflow restoration fixes from v3.5.28 by excluding the visual sigma anchor from positional workflow values.
- Clarify crop behavior: the Sampler's `images` output is hard-cropped to requested width/height after decoding; the `latent` output is unchanged/native and an external VAE Decode (Tiled) requires a subsequent image crop. Add decoded-source diagnostics to the `info` output.
- No changes to the sampling algorithms, image/video save nodes, audio processing, or existing crop calculations; no GitHub or Registry publication.

# v3.5.28 (local test build; not published)

- Fix Lyonir Sampler Ctrl+C/Ctrl+V duplication shifting widget values into neighboring controls (red/invalid parameters).
- Restore workflow widget values by their **names** instead of assuming widget indices remain unchanged after dynamic rearrangement.
- Respect LiteGraph's `widget.serialize` for workflow persistence; `widget.options.serialize` is a separate API/prompt setting and must not filter copied values.
- Preserve old workflow loading, the Basic Scheduler / Manual Sigmas UI and native SIGMAS input, all sampler math and crop behavior, and every other node.
- Do not publish this build to GitHub or ComfyUI Registry before user validation.

# v3.5.27 (local test build; not published)

- Fix missing native `sigmas` input when **Manual Sigmas** is selected in current ComfyUI frontends.
- Remove invalid link from the SIGMAS socket to a non-registered temporary widget (which caused some frontends to delete the input silently).
- Use native input creation/removal, place its connector below Sampling Mode, and retain the normal Basic Scheduler controls and saved workflow compatibility.
- No changes to sampling math, crop, video/audio, other nodes, GitHub, or ComfyUI Registry.

# v3.5.26 (local test build; not published)

- Rename Lyonir Sampler Sampling Mode's normal option to **Basic Scheduler**; preserve the prior **Steps** value as a legacy alias when loading older workflows.
- Arrange **steps**, **scheduler** and **denoise** directly below **Sampling Mode** when Basic Scheduler is active.
- In Manual Sigmas, hide those controls and show the **SIGMAS** input just beneath Sampling Mode; in Basic Scheduler, remove the SIGMAS socket from the visible node.
- Keep the original sigma calculation, external-sigma behavior, sampler algorithm, video/audio processing, and other nodes unchanged.
- Do not publish to GitHub or ComfyUI Registry until user validation.

# v3.5.25 (local test build; not yet published)

- Add **Sampling Mode** dropdown to 🐺 Lyonir Sampler: **Steps** (default, original steps/scheduler/denoise logic) or **Manual Sigmas** (connected SIGMAS tensor only).
- Manual Sigmas bypasses internal sigma calculation and reports actual steps from the supplied tensor. The sampler algorithm, seed/noise, model-specific guider, decoding and cropping remain unchanged.
- Hide steps/scheduler/denoise widgets while Manual Sigmas is selected; restore them on Steps. Preserve existing links, widget values, and workflow compatibility.
- Report a clear input error if Manual Sigmas is chosen without a connected SIGMAS tensor.
- No GitHub or ComfyUI Registry publication in this test build.

# v3.5.24

- Integrate tested Save Video frame counting onto the existing v3.5.23 repository code.
- Show verified total frames, FPS, and duration only in the selected video details (not on history thumbnails).
- Check historical video frame counts asynchronously and preserve gallery playback, encoding, recent format-widget fixes, and Image Compare behavior.
- Preserve all other nodes and packaged media binaries from v3.5.23.
- Local code/synthetic-media checks completed; user ComfyUI validation pending.

# v3.5.23

- Remove A/B badges from Image Compare preview.
- Preserve right-to-left wipe and workflow preview restoration.

# v3.5.22

- Restore Image Compare A/B preview references and wipe position after workflow recreation.
- Reveal B from right to left; labels and context actions follow visible sides.
- Preview restoration requires the original ComfyUI temporary files to remain available.

# v3.5.21

- Remove stale format widgets before creating replacements to prevent #1 suffixes in Save Video.
- Keep preset labels readable while preserving input handling and saved values.

# v3.5.20

- Correct Image Compare labels: B on the revealed left side, A on the right. Moving the wipe left to right progressively reveals B.
- Preserve input mapping, comparison behavior and all other nodes.

# v3.5.19

- Fix Save Image context-menu actions in frontends that consume the options array directly.
- Save Image downloads the selected gallery image; other nodes are unchanged.

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
