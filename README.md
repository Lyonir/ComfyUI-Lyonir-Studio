# 🐺 ComfyUI Lyonir Studio

Custom nodes for **ComfyUI**, created by **Lyonir Studio**.

Current public version: **v3.5.13**.

## Included nodes

- 🐺 Lyonir Sampler
- 🐺 Lyonir Resolution
- 🐺 Lyonir Save Image
- 🐺 Lyonir Save Video
- 🐺 Lyonir Image Compare
- 🐺 Lyonir Qwen3-TTS Voice Clone
- 🐺 Lyonir Qwen3-TTS Voice Design
- 🐺 Lyonir Qwen3-TTS Custom Voice

## Highlights

### Lyonir Save Video

Designed to behave like VideoHelperSuite's **Video Combine** while adding a persistent per-node video history.

- Delegates final encoding to the installed `VHS_VideoCombine`.
- Uses the formats and format-specific controls exposed by Video Combine.
- Adds bit-depth handling where the selected format exposes a controllable pixel format.
- Keeps previous generated videos available as selectable thumbnails.
- Uses a persistent per-node history identity so new nodes do not inherit old histories.
- Proportional preview/node resizing.
- Adjustable thumbnail-size slider.
- VideoHelperSuite-compatible hover audio and **Sync Preview** behavior.
- ProRes presets that manage their own pixel format are delegated to Video Combine instead of aborting the render.

### Lyonir Save Image

Persistent image history directly inside the node, with quick access to previously saved images.

### Lyonir Sampler

Unified custom-sampling workflow for supported model families. See [MULTIMODEL.md](MULTIMODEL.md) for model-family notes.

### Qwen3-TTS

Voice Clone, Voice Design and Custom Voice nodes. Review [NOTICE](NOTICE) and [COMMERCIAL_LICENSES.md](COMMERCIAL_LICENSES.md) before commercial deployment.

## Requirements

- A working **ComfyUI** installation.
- Python dependencies listed in `requirements.txt`.
- **ComfyUI-VideoHelperSuite** for `🐺 Lyonir Save Video`, because that node delegates final video encoding to the installed `VHS_VideoCombine`.

- **Qwen3-TTS voice nodes:** install [ComfyUI-Qwen-TTS](https://github.com/flybirdxx/ComfyUI-Qwen-TTS) and its dependencies in the same ComfyUI environment. This provides the backend used by the voice nodes. Model files are downloaded or configured separately.

Some nodes may require additional model files or upstream packages depending on the workflow.

## Installation

### Git

Open a terminal inside `ComfyUI/custom_nodes` and run:

```bash
git clone https://github.com/Lyonir/ComfyUI-Lyonir-Studio.git
```

Then install the Python requirements using the same Python environment used by ComfyUI:

```bash
pip install -r ComfyUI-Lyonir-Studio/requirements.txt
```

Restart ComfyUI.

### Manual installation

1. Download the repository as ZIP.
2. Extract it.
3. Make sure the final folder is `ComfyUI/custom_nodes/ComfyUI-Lyonir-Studio/`.
4. Install `requirements.txt` using the same Python environment as ComfyUI.
5. Restart ComfyUI.

## Updating

If installed with Git:

```bash
cd ComfyUI/custom_nodes/ComfyUI-Lyonir-Studio
git pull
```

Restart ComfyUI. If frontend files changed, refresh the browser as well.

## Examples

Four downloadable workflows with screenshots and model filenames are available in the [example guide](examples/README.md):

- MiniMax H3 first/last-frame video.
- MiniMax H3 reference-to-video.
- LTX 2.5 video with latent upscale.
- Z-Image Turbo using Lyonir Save Image.

![MiniMax H3 and Lyonir Save Video](examples/screenshots/minimax-video-gallery.png)

Model weights and reference images must be provided separately. See the guide before running an example.

## Troubleshooting

If a node does not appear after installation:

1. Check the ComfyUI terminal for Python import errors.
2. Confirm the repository folder is directly under `ComfyUI/custom_nodes/`.
3. Install `requirements.txt` using the same Python environment as ComfyUI.
4. Restart ComfyUI completely.
5. Refresh the browser frontend.

For `Lyonir Save Video`, also confirm that **ComfyUI-VideoHelperSuite** is installed and `VHS_VideoCombine` is available.

## License

The Lyonir Studio code in this repository is distributed under the license included in [LICENSE](LICENSE).

Model weights, third-party packages, voice data and upstream projects may have their own licenses and usage restrictions. See [NOTICE](NOTICE) and [COMMERCIAL_LICENSES.md](COMMERCIAL_LICENSES.md).

## Creator

**Lyonir Studio**

- Website: https://www.lyonirstudio.com/
- Portfolio: https://lyonirstudios.myportfolio.com/

