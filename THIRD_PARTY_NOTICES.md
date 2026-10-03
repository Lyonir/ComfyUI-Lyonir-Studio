# Third-party notices

This combined distribution is provided under GNU GPL version 3 (LICENSE).
Original Lyonir files retain their Apache-2.0 terms (LICENSE-APACHE-2.0).

The internal video_engine encoder, helpers and video_formats derive from
ComfyUI-VideoHelperSuite, by Kosinkadink and contributors:
https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite
Reference commit: 4d907bee61e92c2e65af3bd6383a4e4d356126d1
Changes: only VideoCombine is included, with internal imports, packaged FFmpeg
selection and Lyonir output recognition in the batch queue helper. Other VHS
nodes and its frontend are not registered or installed.

Windows x64 includes FFmpeg 9.0.2 full_build from Gyan Doshi compressed in the five numbered vendor/ffmpeg-windows-x64.zip archive parts, extracted privately into vendor/runtime.
The original GPLv3 LICENSE and README containing source links, build configuration
and external-library versions are included as vendor/LICENSE-FFmpeg and vendor/README-FFmpeg.txt alongside the compressed archive parts.
Build download: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z
Source: https://github.com/FFmpeg/FFmpeg/commit/946fcce07b
Original archive SHA256: f0e46253c70dfe902bac915dfb4224f0cf1b7c6eeab9da2ccc9a5581f9a71b13
Other operating systems use separately installed imageio-ffmpeg; its license
and source are at https://github.com/imageio/imageio-ffmpeg.

Bundled executable SHA256: 589e50b766d251afdf181dd664d40bd94407e200b019989fd7468c7d118a28d0
