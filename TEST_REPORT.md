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

Sampler total-progress test build: simulated native sampling and repeated tiled VAE progress remained monotonic with a fixed total of 100. Preview payloads were preserved, other-thread updates passed through, and the original progress hook was restored after success and failure. AST comparison confirmed the original generate signature and processing statements are unchanged. Python syntax passed. Real-model generation and live UI validation of this progress update were not run.

User acceptance: the user tested the sampler progress build in their ComfyUI, reported that it was working correctly, and authorized publication. Public release code is identical to that accepted test build; only release documentation differs.

Video metadata validation: tests passed for final-sampler selection, seed zero, exact 64-bit strings, linked primitive inputs, cycles, multiple branches and unavailable metadata. Copy-button tests passed for selected seed, success feedback, selection reset, missing-seed disabling and clipboard failure. JavaScript and Python syntax passed. The user tested the final clean layout and copy button in ComfyUI, approved the result and authorized publication. No encoding changes were made for this release.

3.5.18 validation: Save Image batch saving, actual dimensions, exact seed strings, persisted history, isolated nodes sharing a numeric ID, fresh clone identities, workflow identity reload, old missing metadata, clipboard success and failure, and syntax checks passed. User tested the updated pack and approved publication. Save Video encoding and Sampler behavior are unchanged.
