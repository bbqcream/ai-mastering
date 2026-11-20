"""Classify stems, mix and master audio, or apply panning with AbletonOSC."""
import argparse
import sys
from pathlib import Path

from core.ableton import AbletonOSC
from core.mix import load_mix_plan, render_mix, save_mix_plan, suggest_mix
from core.io import save_audio
from core.pipeline import master_audio


def main():
    parser = argparse.ArgumentParser(description="스템별 믹스 분석 및 렌더링")
    parser.add_argument("stems", help="정렬된 오디오 스템 폴더")
    parser.add_argument("--plan", help="불러올 JSON 믹스 플랜")
    parser.add_argument("--write-plan", help="새 제안 플랜 저장 경로")
    parser.add_argument("-o", "--output", help="스테레오 믹스 WAV 저장 경로")
    parser.add_argument("--master", help="믹스 후 자동 마스터링한 WAV 저장 경로")
    parser.add_argument("--lufs", type=float, default=-14, help="마스터 목표 LUFS (기본 -14)")
    parser.add_argument("--ceiling", type=float, default=-1, help="마스터 트루피크 상한 dBTP (기본 -1)")
    parser.add_argument("--ableton", action="store_true", help="AbletonOSC로 Live 트랙 팬 적용")
    args = parser.parse_args()

    try:
        plan = load_mix_plan(args.plan) if args.plan else suggest_mix(args.stems)
        outputs = [Path(path).resolve() for path in (args.output, args.master, args.write_plan) if path]
        inputs = {(Path(args.stems) / track["file"]).resolve() for track in plan["tracks"]}
        if args.plan:
            inputs.add(Path(args.plan).resolve())
        if len(outputs) != len(set(outputs)) or inputs.intersection(outputs):
            raise ValueError("저장 경로는 입력 파일 및 다른 출력과 달라야 합니다")
        for track in plan["tracks"]:
            result = track.get("analysis", {})
            level = result.get("lufs")
            level_text = f"{level:.1f} LUFS" if level is not None else "측정값 없음"
            effects = ", ".join(entry["effect"] for entry in track.get("effects", [])) or "-"
            print(
                f"{track['name']:<24} {track.get('role', '-'):>14} {level_text:>14}"
                f"  게인 {track.get('gain_db', 0):+5.1f} dB  팬 {track.get('pan', 0):+4.2f}  {effects}"
            )

        if args.write_plan:
            save_mix_plan(args.write_plan, plan)
            print(f"믹스 플랜 저장: {args.write_plan}")
        if args.output or args.master:
            mixed, sample_rate, info = render_mix(args.stems, plan)
            if args.output:
                save_audio(args.output, mixed, sample_rate)
                print(f"믹스 저장: {args.output} ({sample_rate} Hz)")
            if info["safety_gain_db"]:
                print(f"피크 보호 감쇠: {info['safety_gain_db']:.2f} dB")
            if args.master:
                report = master_audio(mixed, sample_rate, args.master, target_lufs=args.lufs, ceiling_db=args.ceiling)
                print(
                    f"마스터 저장: {args.master} "
                    f"({report.after['lufs']:.1f} LUFS, {report.after['true_peak_db']:.1f} dBTP)"
                )
        if args.ableton:
            with AbletonOSC() as live:
                applied = live.apply_panning(plan)
            print(f"Ableton Live 팬 적용: {len(applied)}개 트랙")
    except (OSError, ValueError, RuntimeError) as exc:
        sys.exit(f"오류: {exc}")


if __name__ == "__main__":
    main()
