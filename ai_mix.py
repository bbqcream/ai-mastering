"""Free, local AI stem mixing and mastering entry point."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from core.ai_mix import ai_mix
from core.local_ai import LocalAI
from core.pipeline import master_audio


def main():
    parser = argparse.ArgumentParser(description="무료 로컬 AI 자동 믹싱 및 마스터링")
    parser.add_argument("stems", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("ai-output"))
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--passes", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--lufs", type=float, default=-14)
    parser.add_argument("--ceiling", type=float, default=-1)
    args = parser.parse_args()
    try:
        model = LocalAI(args.model, args.ollama)
        model.check()
        destination = args.output_dir.resolve()
        if destination == args.stems.resolve() or args.stems.resolve() in destination.parents:
            raise ValueError("출력 폴더를 스템 폴더 밖에 지정하세요")
        destination.mkdir(parents=True, exist_ok=False)
        report_path = destination / "report.json"
        report = {"status": "running", "model": args.model}
        try:
            audio, sr, plan, history = ai_mix(args.stems, model, args.passes)
            report.update(history)
            report["plan"] = plan
            master = master_audio(audio, sr, destination / "master.wav", target_lufs=args.lufs, ceiling_db=args.ceiling)
            report["master"] = asdict(master)
            report["status"] = "complete"
            print(f"저장 {destination / 'master.wav'} · {master.after['lufs']:.1f} LUFS · {master.after['true_peak_db']:.1f} dBTP")
        except BaseException as exc:
            report.update(status="failed", error=str(exc))
            raise
        finally:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
