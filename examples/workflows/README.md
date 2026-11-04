# Example workflows

The LTX 2.5 and MiniMax examples use **Basic Scheduler** with their saved settings. For **Manual Sigmas**, select it in Sampling Mode and connect a SIGMAS output to each sampler you switch.

The LTX example targets 1280 x 720. The first sampler passes its native latent to the second stage. The stock VAE decoder applies the exact crop after decoding.

See the [main README](../../README.md#example-workflows) for model and custom node requirements for all examples.
