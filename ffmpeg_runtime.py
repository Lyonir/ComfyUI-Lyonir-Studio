"""Select private FFmpeg; never install packages or change system PATH."""
from pathlib import Path
import hashlib
import os
import platform
import shutil
import tempfile
import zipfile

_WINDOWS_SHA256 = "589e50b766d251afdf181dd664d40bd94407e200b019989fd7468c7d118a28d0"

def _digest(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()

def get_ffmpeg_path():
    root = Path(__file__).resolve().parent
    if platform.system() == 'Windows' and platform.machine().lower() in ('amd64', 'x86_64'):
        archive_path = root / 'vendor' / 'ffmpeg-windows-x64.zip'
        binary = root / 'vendor' / 'runtime' / 'ffmpeg.exe'
        parts = sorted((root / 'vendor').glob('ffmpeg-windows-x64.zip.[0-9][0-9][0-9]'))
        if archive_path.is_file() or parts:
            if binary.is_file():
                with binary.open('rb') as stream:
                    if _digest(stream) == _WINDOWS_SHA256:
                        return str(binary)
            binary.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=binary.parent, suffix='.tmp', delete=False) as output:
                    temporary = Path(output.name)
                    with tempfile.TemporaryFile(dir=binary.parent) as assembled:
                        if archive_path.is_file():
                            with archive_path.open('rb') as part:
                                shutil.copyfileobj(part, assembled)
                        else:
                            for expected, part_path in enumerate(parts, 1):
                                if part_path.suffix != f'.{expected:03d}':
                                    raise RuntimeError('Bundled FFmpeg part missing; reinstall the complete pack.')
                                with part_path.open('rb') as part:
                                    shutil.copyfileobj(part, assembled)
                        assembled.seek(0)
                        with zipfile.ZipFile(assembled) as archive, archive.open('ffmpeg.exe') as source:
                            shutil.copyfileobj(source, output)
                with temporary.open('rb') as stream:
                    digest = _digest(stream)
                if digest != _WINDOWS_SHA256:
                    raise RuntimeError('Bundled FFmpeg checksum mismatch; reinstall the Lyonir Studio pack.')
                os.replace(temporary, binary)
                return str(binary)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
        raise RuntimeError('Bundled FFmpeg archive missing; reinstall the complete Lyonir Studio pack.')
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None
