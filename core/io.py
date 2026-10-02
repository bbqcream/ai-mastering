from pathlib import Path

import numpy as np
import soundfile as sf


def load_audio(path):
    """(samples, channels) float32 배열과 샘플레이트를 반환."""
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    return y, sr


def load_stems(directory):
    """같은 시작점과 길이로 내보낸 오디오 스템을 합산한다."""
    folder = Path(directory)
    extensions = {".wav", ".aif", ".aiff", ".flac"}
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in extensions)
    if not paths:
        raise ValueError(f"스템 폴더에 WAV/AIFF/FLAC 파일이 없습니다: {folder}")

    stems = []
    sample_rate = None
    shape = None
    for path in paths:
        audio, sr = load_audio(path)
        if sample_rate is None:
            sample_rate = sr
            shape = audio.shape
        elif sr != sample_rate or audio.shape != shape:
            raise ValueError(
                f"스템 형식이 서로 다릅니다: {path.name}. "
                "모든 스템을 같은 샘플레이트, 채널 수, 시작점, 길이로 내보내세요."
            )
        stems.append(audio)

    mix = np.zeros(shape, dtype=np.float32)
    for stem in stems:
        mix += stem
    return mix, sample_rate, [path.name for path in paths]


def save_audio(path, y, sr, subtype="PCM_24"):
    sf.write(path, y, sr, subtype=subtype)
