import soundfile as sf


def load_audio(path):
    """(samples, channels) float32 배열과 샘플레이트를 반환."""
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    return y, sr


def save_audio(path, y, sr, subtype="PCM_24"):
    sf.write(path, y, sr, subtype=subtype)
