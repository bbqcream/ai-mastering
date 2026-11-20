"""Apply role-based fader and pan settings through Ableton MCP Extended."""

import argparse
import asyncio
import json
import math

from core.roles import PROFILES, classify_track, track_pan


async def _call(session, tool, **arguments):
    result = await asyncio.wait_for(session.call_tool(tool, arguments), timeout=15)
    message = "\n".join(part.text for part in result.content if part.type == "text")
    if result.isError or message.lstrip().lower().startswith("error"):
        raise RuntimeError(f"{tool}: {message}")
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return message
    return data


async def _read_mixer(session, index, expected_name=None):
    mixer = await _call(session, "get_mixer", track_index=index)
    if not isinstance(mixer, dict) or not isinstance(mixer.get("name"), str):
        raise RuntimeError(f"트랙 {index + 1}의 믹서 응답을 읽을 수 없습니다")
    if expected_name is not None and mixer["name"] != expected_name:
        raise RuntimeError(f"트랙 {index + 1}의 이름 또는 순서가 변경되었습니다")
    return mixer


async def _mix(session, dry_run):
    required = {"get_session_info", "get_mixer", "set_track_volume", "set_track_panning"}
    page = await asyncio.wait_for(session.list_tools(), timeout=15)
    tools = {tool.name for tool in page.tools}
    while page.nextCursor:
        page = await asyncio.wait_for(session.list_tools(cursor=page.nextCursor), timeout=15)
        tools.update(tool.name for tool in page.tools)
    if required - tools:
        raise RuntimeError("Ableton MCP Extended 필수 도구 누락: " + ", ".join(sorted(required - tools)))

    info = await _call(session, "get_session_info")
    if not isinstance(info, dict) or type(info.get("track_count")) is not int or info["track_count"] < 0:
        raise RuntimeError("Ableton 세션의 트랙 수를 읽을 수 없습니다")

    plan = []
    positions = {}
    for index in range(info["track_count"]):
        mixer = await _read_mixer(session, index)
        name = mixer["name"]
        role = classify_track(name)
        if mixer.get("is_group") or role == "unknown":
            print(f"{index + 1:>3} {name}  ({'그룹' if mixer.get('is_group') else '미분류'}) 건너뜀")
            continue
        volume = float(mixer["volume"]["value"])
        pan = float(mixer["panning"]["value"])
        if not 0 <= volume <= 1 or not -1 <= pan <= 1:
            raise RuntimeError(f"{name}: 믹서 값이 유효하지 않습니다")
        if volume == 0:
            print(f"{index + 1:>3} {name}  (페이더 -∞) 건너뜀")
            continue
        profile = PROFILES[role]
        position = positions.get(role, 0)
        target_pan = track_pan(name, profile, position)
        positions[role] = position + 1
        plan.append((index, name, volume, pan, profile.fader, target_pan))
        print(f"{index + 1:>3} {name}  {role}  {profile.fader:+.1f} dB  팬 {target_pan:+.2f}")

    if dry_run:
        print(f"예상 적용 {len(plan)}개 트랙")
        return

    changed = []
    try:
        for index, name, volume, pan, target_db, target_pan in plan:
            current = await _read_mixer(session, index, name)
            if abs(current["volume"]["value"] - volume) > 0.001 or abs(current["panning"]["value"] - pan) > 0.001:
                raise RuntimeError(f"{name}: 계획을 생성한 뒤 믹서 값이 변경되었습니다")
            db = current["volume"].get("db")
            if db is not None and math.isclose(db, target_db, abs_tol=0.1) and math.isclose(pan, target_pan, abs_tol=0.01):
                continue
            changed.append((index, name, volume, pan))
            await _call(session, "set_track_volume", track_index=index, db=target_db)
            await _call(session, "set_track_panning", track_index=index, value=target_pan)
            applied = await _read_mixer(session, index, name)
            db = applied["volume"].get("db")
            if db is None or not math.isclose(db, target_db, abs_tol=0.1):
                raise RuntimeError(f"{name}: 페이더 적용값을 확인하지 못했습니다")
            if not math.isclose(applied["panning"]["value"], target_pan, abs_tol=0.01):
                raise RuntimeError(f"{name}: 팬 적용값을 확인하지 못했습니다")
    except Exception as exc:
        unrestored = []
        for index, name, volume, pan in reversed(changed):
            try:
                await _read_mixer(session, index, name)
                await _call(session, "set_track_volume", track_index=index, value=volume)
                await _call(session, "set_track_panning", track_index=index, value=pan)
                restored = await _read_mixer(session, index, name)
                if (abs(restored["volume"]["value"] - volume) > 0.001
                        or abs(restored["panning"]["value"] - pan) > 0.001):
                    unrestored.append(name)
            except Exception:
                unrestored.append(name)
        status = f"복구 확인 필요: {', '.join(unrestored)}" if unrestored else "이전 믹서 값 복구 완료"
        raise RuntimeError(f"Live 자동 믹스 중단 ({status}): {exc}") from exc
    print(f"Live 믹서 변경 {len(changed)}개 트랙, 기존값 일치 {len(plan) - len(changed)}개 트랙")


async def _run(command, dry_run):
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ModuleNotFoundError as exc:
        if exc.name != "mcp":
            raise
        raise RuntimeError('MCP 클라이언트를 설치하세요: python -m pip install "mcp>=1.9,<2"') from exc

    params = StdioServerParameters(command=command[0], args=command[1:], env={
        "ABLETON_MCP_DISABLE_TELEMETRY": "true",
        "DISABLE_TELEMETRY": "true",
        "ABLETON_MCP_ENABLE_DATASET": "false",
    })
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=120)
            await _mix(session, dry_run)


def main():
    parser = argparse.ArgumentParser(description="Ableton MCP로 트랙명 기반 게인 및 팬 적용")
    parser.add_argument("--dry-run", action="store_true", help="Live 트랙을 읽고 적용안만 출력")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- 뒤에 Ableton MCP 서버 명령")
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("-- 뒤에 Ableton MCP Extended 서버 명령을 입력하세요")
    try:
        asyncio.run(_run(command, args.dry_run))
    except Exception as exc:
        while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
            exc = exc.exceptions[0]
        parser.exit(1, f"오류: {exc or type(exc).__name__}\n")


if __name__ == "__main__":
    main()
