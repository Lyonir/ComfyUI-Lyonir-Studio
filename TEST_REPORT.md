## v3.5.31 local regression tests (2026-11-04; not published)

- Diagnosis: v3.5.30 VAE decode→pixel crop→VAE re-encode truncated LTX spatial pixels from 720 to 704 because height 720 is not divisible by LTX VAE factor 32; lossy re-encode could also introduce image artifacts.
- Fix: revert to the v3.5.29/v3.5.24 sampling backend and **remove VAE re-encoding** entirely. LATENT samples remain unchanged; attach exact final crop metadata to the LATENT dict.
- The same hard pixel crop runs on IMAGE output and on output of ComfyUI stock VAEDecode / VAEDecodeTiled when provided a marked LATENT, including after LTXVSeparateAVLatent (which copies the dict). No workflow crop node required for these builtin decoders.
- Synthetic regression: 1280x768 native LTX sample is decoded and cropped to exactly 1280x720, including center/top/bottom anchor; unmarked inputs remain native, input LATENT tensor identity preserved, undersized decoded dimensions fail loudly.
- Two-stage simulated LTX workflow: Stage 1 Basic Scheduler target 640x360, Stage 2 Manual Sigmas target 1280x720, stock tiled decoder output exactly 1280x720. No re-encoding.
- JavaScript interface simulation: SIGMAS widget row beneath Sampling Mode, steps/scheduler/denoise only when Basic, Ctrl+C/Ctrl+V restoration.
- Packaging and Python syntax checked. **Real LTX 2.3 execution and visual quality on the user's Windows RTX 3090 have not been tested**; GPU acceptance pending.
- Scope: builtin VAEDecode and VAEDecodeTiled only. Third-party VAE decoder implementations may ignore crop metadata. LTX LATENT grid cannot physically store an arbitrary 720-pixel height: exact output is enforced after decode.
- No GitHub/Registry publication.

## v3.5.29: Sampling Mode visual row and crop scope

- Current ComfyUI Vue frontend renders non-widget SIGMAS sockets in the upper socket list even when `slot.pos` / `getConnectionPos` changes. This fix attaches SIGMAS to a **real, non-serialized widget row** immediately under Sampling Mode, and keeps the input type `SIGMAS` and its graph link compatibility.
- Frontend regression harness: manual SIGMAS is widget-backed (thus absent from Vue top-level socket list); row immediately follows Sampling Mode; Basic Scheduler hides it; copy/paste and legacy mode restoration preserve widgets; step controls only appear in Basic Scheduler.
- Backend crop regression: tests cover exact width and height for center/top-left/bottom-right crop anchors, preservation of pixel values (hard crop rather than resize), and proper error on undersized frames. The output of `latent` is intentionally not cropped; a subsequent external VAE Decode needs a downstream image crop.
- Live ComfyUI frontend validation on the user's Windows setup remains pending. No GitHub/Registry publication.

## v3.5.28: Lyonir Sampler copy/paste widget restoration regression

- Correctly distinguish LiteGraph `widget.serialize` (workflow persistence) from `widget.options.serialize` (API prompt persistence).
- Persist named values and the serialized widget order; use named values preferentially when restoring nodes (including Ctrl+C / Ctrl+V and workflow reopening).
- Fallback for legacy positional-only workflows, including v3.5.26/v3.5.27 and original-schema layouts.
- Automated `node` harness tested native SIGMAS port visibility, Basic Scheduler/Manual Sigmas alternation, repeat duplication, out-of-order positional data, and the seed's `control_after_generate` auxiliary widget.
- Backend Python and JavaScript syntax verified; complete 73-entry ZIP checked; files outside the six changed files plus TEST_REPORT remain byte-identical to the approved v3.5.27 release.
- **User verification still required:** Ctrl+C / Ctrl+V and workflow reloading in the actual ComfyUI frontend on Windows. Tests simulate frontend behavior and are not a replacement for that verification.
- **Not published** to GitHub or ComfyUI Registry.

## v3.5.27 regression: Manual Sigmas port visibility
- Native SIGMAS socket is no longer associated with an unregistered widget anchor.
- UI uses native addInput/removeInput and explicit connector positioning directly below Sampling Mode.
- Existing Basic Scheduler behavior, legacy label conversion and workflow widgets remain unchanged.
- Automated tests: see console/test logs when run; real ComfyUI Windows UI verification still required.

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

3.5.19 validation: menu mutation, inherited menus, single Save Image action, empty-gallery behavior, selected-image callback and download link checks passed. JavaScript syntax passed. The user installed the test pack in ComfyUI and confirmed that it works.

3.5.20 validation: frontend simulation verified actual A/B input mapping, wipe positions at 0/25/50/75/100 percent, divider and label positions. JavaScript syntax passed. Only Image Compare labels and release metadata changed from 3.5.19.

3.5.21 validation: simulated name-deduplicating widget constructors passed repeated rebuilds, clean names and labels, format switching, input cleanup and named-value restore (CRF 7, 10-bit pixel format and metadata disabled). JavaScript syntax passed. Live ComfyUI visual validation was not performed for this change.

3.5.22 validation: simulated right-to-left reveal endpoints, A/B labels, workflow serialization and preview restore, saved wipe position and unrelated empty workflow isolation passed. Python and JavaScript syntax passed. The user installed the complete test pack and confirmed correct behavior in ComfyUI, including the requested fixes. Release Image Compare code is identical to the accepted test pack.

3.5.23 validation: only Image Compare label creation and visibility removed from runtime code. JavaScript syntax passed. Wipe and preview restoration code unchanged. Live visual validation not performed.

3.5.24 validation: the change was rebased onto the user-uploaded v3.5.23 ZIP. Only Save Video backend/frontend, version references and release documentation were changed. Automated syntax, archive-integrity and synthetic FFmpeg/FFprobe frame-count tests are documented by this build. User live ComfyUI validation is pending.

### v3.5.25 local test build (Sampling Mode)

- Python sampler code compiled successfully; all four frontend JS files pass `node --check`.
- Nine mocked backend tests passed: unchanged Steps route, connected Manual Sigmas schedule without internal sigma calculation, effective steps, no-sigmas error, invalid-sigmas error, manual/Steps MiniMax guider behavior, Steps ignoring sigmas when connected, and default legacy mode.
- Frontend harness passed: mode widget callback, hide/show steps/scheduler/denoise, graph restore, link target slot preservation, and no widget reordering.
- No live ComfyUI/GPU test was performed in the build environment. Please test manually before any GitHub/Registry publication.

### v3.5.27 local test build (Basic Scheduler / SIGMAS layout)

- Based on the full user-approved v3.5.25 ZIP, preserving the pack's other nodes and bundled media.
- Backend Python tests: 10 passed, covering Basic Scheduler, Manual Sigmas, MiniMax behavior, invalid/missing sigmas, legacy `Steps` alias.
- Frontend harness: Basic Scheduler controls directly beneath Sampling Mode; only Manual Sigmas exposes SIGMAS input and reserves a row directly beneath the selector; legacy/current workflow widget values reload correctly.
- Node.js JS syntax and Python compilation checks passed. ZIP integrity check performed.
- **Live ComfyUI GUI validation has not been performed**; test input position/connectivity and Save/Reload in the user's frontend before publishing.
- **No GitHub or Registry changes made.**
