"""파일 하나를 분석 -> 조정안 -> (승인) -> 적용 -> 저장까지 한 번에 처리."""
import numpy as np

from . import master
from .io import load_audio, load_stems, save_audio
from .types import Report


def run_master(
    in_path,
    out_path,
    ref_path=None,
    target_lufs=-14.0,
    ceiling_db=-1.0,
    confirm=None,
    dry_run=False,
    ab_path=None,
):
    """confirm: 조정안 목록을 받아 승인 상태를 바꿔 돌려주는 함수(CLI/웹 UI가 넘김).
    dry_run: 분석과 제안만 하고 파일은 만들지 않는다.
    ab_path: 원본을 결과와 같은 라우드니스로 맞춘 비교용 파일 경로.
    """
    if hasattr(in_path, "is_dir") and in_path.is_dir():
        y, sr, stem_names = load_stems(in_path)
    else:
        y, sr = load_audio(in_path)
        stem_names = None

    report = master_audio(y, sr, out_path, ref_path, target_lufs, ceiling_db, confirm, dry_run, ab_path)
    if stem_names:
        report.info["stems"] = stem_names
    return report


def master_audio(
    y, sr, out_path, ref_path=None, target_lufs=-14.0, ceiling_db=-1.0,
    confirm=None, dry_run=False, ab_path=None,
):
    """Master an in-memory mix without a lossy intermediate file."""
    if not np.isfinite(target_lufs) or not -70 < target_lufs <= 0:
        raise ValueError("목표 LUFS는 -70보다 크고 0 이하여야 합니다")
    if not np.isfinite(ceiling_db) or not -24 <= ceiling_db <= 0:
        raise ValueError("트루피크 상한은 -24~0dBTP 범위여야 합니다")
    # Loudness measurement needs at least one 400 ms block.
    length = len(y)
    pad = max(0, int(np.ceil(sr * 0.4)) - length)
    if pad:
        y = np.pad(y, ((0, pad), (0, 0)))
    before = master.analyze(y, sr)
    ref = None
    if ref_path:
        ry, rsr = load_audio(ref_path)
        ref = master.analyze(ry, rsr)

    plan = master.suggest(before, ref, target_lufs, ceiling_db)
    if dry_run:
        return Report(before=before, adjustments=plan)

    if confirm:
        plan = confirm(plan)

    out, info = master.render(y, sr, plan)
    if pad:
        # Measure a zero-padded copy of the actual output, as for the input.
        out[length:] = 0
    after = master.analyze(out, sr)
    save_audio(out_path, out[:length], sr)

    if ab_path:
        info["ab_note"] = _save_ab(y[:length], sr, after["lufs"], before["lufs"], ab_path)

    return Report(before=before, after=after, adjustments=plan, info=info)


def _save_ab(y, sr, out_lufs, orig_lufs, path):
    """원본을 결과와 같은 라우드니스로 맞춰 저장(공정한 A/B 비교용)."""
    gain = 10 ** ((out_lufs - orig_lufs) / 20)
    matched = y * gain
    peak = float(np.max(np.abs(matched)))
    note = ""
    if peak > 0.99:
        matched = matched * (0.99 / peak)
        note = "원본을 결과 라우드니스까지 올리면 0dBFS를 넘어서 클리핑 방지로 조금 낮춰 저장함(라우드니스가 완전히 같지는 않음)"
    save_audio(path, matched, sr)
    return note
