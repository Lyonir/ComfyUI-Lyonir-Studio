# Example workflows

The LTX 2.5 and MiniMax examples use **Basic Scheduler** with their saved settings. For **Manual Sigmas**, select it in Sampling Mode and connect a SIGMAS output to each sampler you switch.

The LTX example targets 1280 x 720. The first sampler passes its native latent to the second stage. The stock VAE decoder applies the exact crop after decoding.

See the [main README](../../README.md#example-workflows) for model and custom node requirements for all examples.

## Drawbox image editing

[Download the FLUX.2 Klein 4B FP8 example](Lyonir%20-%20Image%20Edit%20Boxes%20Flux%202%20Klein%204b%20FP8.json). Requires Lyonir Studio v3.5.32+, ComfyUI-Inpaint-CropAndStitch and the models listed in the [illustrated setup](../../README.md#drawbox-image-editing-with-flux2-klein-4b-fp8). Select your own input image.
