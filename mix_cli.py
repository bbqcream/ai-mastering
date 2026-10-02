"""Create a stem mix plan, render it, or apply its panning to Ableton Live."""
import argparse
import sys
from pathlib import Path

from core.ableton import AbletonOSC
from core.mix import load_mix_plan, render_mix, save_mix_plan, suggest_mix
from core.io import save_audio


def main():
    parser = argparse.ArgumentParser(description="스템별 믹스 분석 및 렌더링")
    parser.add_argument("stems", help="정렬된 오디오 스템 폴더")
    parser.add_argument("--plan", help="불러올 JSON 믹스 플랜")
    parser.add_argument("--write-plan", help="새 제안 플랜 저장 경로")
    parser.add_argument("-o", "--output", help="스테레오 믹스 WAV 저장 경로")
    parser.add_argument("--ableton", action="store_true", help="AbletonOSC로 Live 트랙 팬 적용")
    args = parser.parse_args()

    try:
        plan = load_mix_plan(args.plan) if args.plan else suggest_mix(args.stems)
        for track in plan["tracks"]:
            result = track.get("analysis", {})
            level = result.get("lufs")
            level_text = f"{level:.1f} LUFS" if level is not None else "측정값 없음"
            print(f"{track['name']:<24} {level_text:>14}  게인 {track.get('gain_db', 0):+5.1f} dB  팬 {track.get('pan', 0):+4.2f}")

        if args.write_plan:
            save_mix_plan(args.write_plan, plan)
            print(f"믹스 플랜 저장: {args.write_plan}")
        if args.output:
            mixed, sample_rate, info = render_mix(args.stems, plan)
            save_audio(args.output, mixed, sample_rate)
            print(f"믹스 저장: {args.output} ({sample_rate} Hz)")
            if info["safety_gain_db"]:
                print(f"피크 보호 감쇠: {info['safety_gain_db']:.2f} dB")
        if args.ableton:
            with AbletonOSC() as live:
                applied = live.apply_panning(plan)
            print(f"Ableton Live 팬 적용: {len(applied)}개 트랙")
    except (OSError, ValueError, RuntimeError) as exc:
        sys.exit(f"오류: {exc}")


if __name__ == "__main__":
    main()