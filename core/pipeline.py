"""파일 하나를 분석 -> 조정안 -> (승인) -> 적용 -> 저장까지 한 번에 처리."""
import numpy as np

from . import master
from .io import load_audio, save_audio
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
    y, sr = load_audio(in_path)
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
    save_audio(out_path, out, sr)
    after = master.analyze(out, sr)

    if ab_path:
        info["ab_note"] = _save_ab(y, sr, after["lufs"], before["lufs"], ab_path)

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
