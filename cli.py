"""사용법: python cli.py mix.wav [--ref ref.wav] [--lufs -14] [-o out.wav] [--yes] [--dry-run] [--ab]"""
import argparse
import sys
from pathlib import Path

from core.pipeline import run_master


def fmt(a):
    b = a["bands_db"]
    bands = " ".join(f"{k}:{v:+.1f}" for k, v in b.items())
    return (
        f"LUFS {a['lufs']:.1f} | 트루피크 {a['true_peak_db']:.1f}dBTP | "
        f"PLR {a['plr_db']:.1f}dB\n    대역(전체 대비 dB) {bands}"
    )


def confirm(adjs):
    print("\n[조정안]")
    for i, a in enumerate(adjs, 1):
        print(f"  {i}. {a.effect:<14} {a.params}\n     -> {a.reason}")
    ans = input("\n제외할 번호(쉼표로 구분, Enter=전부 적용): ").replace(" ", "")
    exclude = {int(x) for x in ans.split(",") if x.isdigit()}
    for i, a in enumerate(adjs, 1):
        a.approved = i not in exclude
    return adjs


def main():
    p = argparse.ArgumentParser(description="마스터링 분석/제안/적용")
    p.add_argument("input")
    p.add_argument("--ref", help="참고곡(톤 밸런스 비교용)")
    p.add_argument("--lufs", type=float, default=-14.0, help="타깃 라우드니스 (기본 -14)")
    p.add_argument("--ceiling", type=float, default=-1.0, help="트루피크 상한 dBTP (기본 -1)")
    p.add_argument("-o", "--output")
    p.add_argument("--yes", action="store_true", help="승인 질문 없이 전부 적용")
    p.add_argument("--dry-run", action="store_true", help="분석과 제안만 출력")
    p.add_argument("--ab", action="store_true", help="라우드니스를 맞춘 원본 비교 파일도 저장")
    args = p.parse_args()

    src = Path(args.input)
    out = Path(args.output) if args.output else src.with_name(src.stem + "_master.wav")
    ab = src.with_name(src.stem + "_orig_matched.wav") if args.ab else None

    try:
        rep = run_master(
            src, out, args.ref, args.lufs, args.ceiling,
            confirm=None if (args.yes or args.dry_run) else confirm,
            dry_run=args.dry_run, ab_path=ab,
        )
    except ValueError as e:
        sys.exit(f"오류: {e}")

    print("\n[분석: 처리 전]\n    " + fmt(rep.before))
    if args.dry_run:
        print("\n[제안]")
        for i, a in enumerate(rep.adjustments, 1):
            print(f"  {i}. {a.effect:<14} {a.params}\n     -> {a.reason}")
        return

    print("\n[분석: 처리 후]\n    " + fmt(rep.after))
    g = rep.info.get("pre_limiter_gain_db")
    if g is not None:
        print(f"\n리미터 앞단 게인 {g:+.1f}dB")
        if g > 8:
            print("  ⚠ 게인이 큰 편이에요. 리미터가 많이 걸려 소리가 눌릴 수 있으니 믹스 단계에서 다이내믹을 확인해보세요.")
    if rep.info.get("trim_db"):
        print(f"  트루피크 상한을 지키려고 {rep.info['trim_db']:.2f}dB 추가로 낮춤")
    print(f"\n저장: {out}")
    if ab:
        print(f"비교용 원본(라우드니스 맞춤): {ab}")
        if rep.info.get("ab_note"):
            print("  " + rep.info["ab_note"])


if __name__ == "__main__":
    main()
