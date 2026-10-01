# Lyonir Sampler v3.0 — Multi-model modes

## model_family
- `auto`: tries to detect MiniMax H3, LTX, Bernini/Wan from model/latent metadata.
- `minimax`: frozen v2.8 MiniMax H3 sampling path (BasicGuider, one pass).
- `ltx`: generic custom-sampling path; connect `negative` for CFGGuider and `sigmas` when the workflow uses ManualSigmas.
- `bernini`: supports one model or a high-noise `model` + low-noise `secondary_model`, split by `split_step`.
- `wan`: same dual-model option for Wan 2.2 high/low noise workflows.

## Required inputs
`model`, `conditioning`, `latent`, `video_vae`, `target_width`, `target_height`, `model_family`, `seed`, `noise`, `steps`, `sampler_name`, `scheduler`, `denoise`, `crop_anchor`.

## Optional inputs
- `audio_vae`: MiniMax/LTX joint AV decode.
- `negative`: enables native CFGGuider outside the frozen MiniMax path.
- `sigmas`: exact external SIGMAS; bypasses BasicScheduler calculation.
- `cfg`: CFGGuider scale when `negative` is connected.
- `secondary_model`: low-noise second model for Bernini/Wan.
- `split_step`: SplitSigmas-compatible boundary for the dual-model route.

## Outputs
- `images`: decoded and hard-cropped final frames.
- `audio`: decoded audio when a joint AV latent + audio VAE are present; otherwise None.
- `latent`: final sampled latent, intentionally preserved for downstream nodes such as Separate AV Latent, latent upsamplers, second stages, etc.
- `info`: detected/forced family and sampling diagnostics.

## Resolution
Lyonir Resolution still has only `width` and `height`. The same two outputs can be fanned out to both the upstream generation/conditioning node and Lyonir Sampler. Internally the numeric value is rounded up to a 32px-native canvas while the requested exact pixel size is carried as metadata for final hard crop.

## Important
No silent resize/upscale is performed. The decoded native canvas must be at least as large as the requested final size.


### LTX native resolution policy (v3.2.2)
`model_family=ltx` uses a 64-pixel native grid. LTX spatial latents are 32x compressed, and IC-LoRA with a downscale factor of 2 requires even latent width/height. Thus 720x1280 final becomes 768x1280 native and is hard-cropped back to 720x1280 after decode.

### LTX IC-LoRA post-sampling policy (v3.2.2)

When LTX conditioning contains IC-LoRA guide keyframes, Lyonir removes those temporary guide latent slices after sampling and before VAE decode. Joint audio/video latents keep the audio stream intact.
