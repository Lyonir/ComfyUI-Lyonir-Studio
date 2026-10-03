# Local test report

Tested using the Python already available in the Desktop ComfyUI Portable,
with test outputs stored only in the Codex workspace. No Python packages were
installed into either ComfyUI environment. Program Files was not modified.

Passed: MP4 with audio (audio decoded and verified), silent MP4, actual 10-bit
output, temporary output, ping-pong, GIF, lossless WebP, ProRes, FFV1 16-bit,
8/16-bit PNG sequences, H.265, WebM with audio, FFmpeg GIF, loop frame count,
latent/VAE input, alpha channel, and a two-part Meta Batch with requeue.
Gallery history payloads were checked for all completed outputs.
The complete input schema (defaults, dynamic format widgets and output ports)
was compared with the previous pack's wrapper and matches.

The VideoCombine class matches the pinned reference source's AST. Its imports
are internal; no external VHS node is registered during these tests. The
original Lyonir frontend files are unchanged. Existing example workflows
retain their values and connections. See THIRD_PARTY_NOTICES.md for source.

Also passed after switching to full FFmpeg: software AV1, NVIDIA H.264 and HEVC.
NVIDIA AV1 is present but cannot run on this test GPU (No capable devices found).
Actual Desktop ComfyUI startup succeeded with only this pack whitelisted and
no VHS installed. A browser workflow generated two videos, restored the history
on workflow reload, and switching thumbnails changed playback to the older file.

Remaining user validation: real-model VAE generation, NVENC AV1 on supported hardware, optional gifski, custom
third-party presets and longer recordings. Passing these synthetic tests does
not guarantee identical behavior on every machine or every upstream VHS fork.

Fixes in the wrapper: PNG-sequence history resolves the first frame instead
of treating the filename pattern as a missing file. When ffprobe is unavailable,
bundled FFmpeg supplies basic output stream information for bit-depth checks.

Public packaging validation: the compressed Windows FFmpeg extracted with its expected SHA256; all 18 encoding cases passed again using this private extracted binary. The four published example JSON workflows match the repository snapshots; the three video examples passed with their saved export settings and synthetic media. Full real-model generation was not run.

Numbered archive parts: private automatic assembly and SHA256 verification passed from an empty executable cache, followed by all 18 encoding cases again. The executable is identical to the previous tested full build.
