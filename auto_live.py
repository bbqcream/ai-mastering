"""Autonomous Ableton mixing using local Ollama inference and MCP."""

import argparse
import asyncio
import math

from core.local_ai import LocalAI


async def run(args, command):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from core.live_agent import run_agent

    model = LocalAI(args.model, args.ollama)
    await asyncio.to_thread(model.check)
    server = StdioServerParameters(command=command[0], args=command[1:], env={
        "ABLETON_MCP_DISABLE_TELEMETRY": "true", "DISABLE_TELEMETRY": "true",
        "ABLETON_MCP_ENABLE_DATASET": "false",
    })
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=120)
            report = await run_agent(session, model, args.output_dir, args.start_beats, args.end_beats,
                                     args.max_steps, args.loopback_device, args.lufs, args.ceiling)
            print(f"완료 · {args.output_dir}/master.wav · {report['master']['after']['lufs']:.1f} LUFS")


def main():
    parser = argparse.ArgumentParser(description="무료 로컬 AI로 Ableton 트랙 자동 믹싱 및 마스터 출력")
    parser.add_argument("--output-dir", default="live-ai-output")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--start-beats", type=float, default=0)
    parser.add_argument("--end-beats", type=float)
    parser.add_argument("--max-steps", type=int, default=120)
    parser.add_argument("--loopback-device", help="Live 출력이 연결된 Windows 재생 장치 ID")
    parser.add_argument("--lufs", type=float, default=-14)
    parser.add_argument("--ceiling", type=float, default=-1)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        command = ["uvx", "--from", "git+https://github.com/staminna/ableton-mcp-extended.git", "ableton-mcp-extended"]
    if args.max_steps < 1:
        parser.error("--max-steps는 1 이상이어야 합니다")
    if not math.isfinite(args.start_beats) or args.start_beats < 0:
        parser.error("--start-beats는 0 이상의 유한한 숫자여야 합니다")
    if args.end_beats is not None and (not math.isfinite(args.end_beats) or args.end_beats <= args.start_beats):
        parser.error("--end-beats는 시작 위치보다 큰 유한한 숫자여야 합니다")
    if not math.isfinite(args.lufs) or not -70 < args.lufs <= 0:
        parser.error("--lufs는 -70보다 크고 0 이하여야 합니다")
    if not math.isfinite(args.ceiling) or not -24 <= args.ceiling <= 0:
        parser.error("--ceiling은 -24~0 범위여야 합니다")
    try:
        asyncio.run(run(args, command))
    except Exception as exc:
        while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
            exc = exc.exceptions[0]
        parser.exit(1, f"오류: {exc or type(exc).__name__}\n")


if __name__ == "__main__":
    main()
