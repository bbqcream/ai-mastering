"""Add displayed parameter values to an installed Ableton MCP Remote Script."""

import argparse
import ast
import os
from pathlib import Path


MARKER = "# AI_MASTERING_PARAMETER_DISPLAY_V1"


def patch_source(source):
    if MARKER in source:
        return source
    module = ast.parse(source)
    classes = [node.name for node in module.body if isinstance(node, ast.ClassDef)
               and any(isinstance(child, ast.FunctionDef) and child.name == "_serialize_device" for child in node.body)]
    if len(classes) != 1:
        raise ValueError("지원하는 Ableton MCP 디바이스 직렬화 함수를 찾지 못했습니다")
    extension = '''

# AI_MASTERING_PARAMETER_DISPLAY_V1
_ai_mix_original_serializer = CLASS_NAME._serialize_device

def _ai_mix_serializer(self, device, *args, **kwargs):
    result = _ai_mix_original_serializer(self, device, *args, **kwargs)
    for entry in result.get("parameters", []):
        try:
            parameter = device.parameters[entry["index"]]
            entry["value_string"] = parameter.str_for_value(parameter.value)
            if parameter.is_quantized:
                entry["value_items"] = list(parameter.value_items)
        except Exception:
            pass
    return result

CLASS_NAME._serialize_device = _ai_mix_serializer
'''.replace("CLASS_NAME", classes[0])
    updated = source.rstrip() + extension
    compile(updated, "AbletonMCP/__init__.py", "exec")
    return updated


def install(script):
    script = Path(script).resolve(strict=True)
    source = script.read_text(encoding="utf-8-sig")
    updated = patch_source(source)
    if updated == source:
        return False
    backup = script.with_name(script.name + ".ai-mix-backup")
    if not backup.exists():
        backup.write_bytes(script.read_bytes())
    temporary = script.with_name(script.name + ".ai-mix-tmp")
    temporary.write_text(updated, encoding="utf-8")
    os.replace(temporary, script)
    return True


def main():
    parser = argparse.ArgumentParser(description="Ableton MCP에 실제 파라미터 표시값과 선택 항목 지원 추가")
    parser.add_argument("--script", type=Path, help="설치된 AbletonMCP/__init__.py 경로")
    args = parser.parse_args()
    try:
        if args.script:
            scripts = [args.script]
        else:
            root = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Ableton"
            scripts = sorted(root.glob("Live*/Preferences/User Remote Scripts/AbletonMCP/__init__.py"))
        if not scripts:
            raise ValueError("Ableton MCP Remote Script를 먼저 설치하세요. 다른 위치라면 --script로 지정하세요")
        for script in scripts:
            changed = install(script)
            print(f"{'지원 추가 완료' if changed else '이미 지원됨'} · {script}")
        print("Ableton Live를 재시작하면 표시값과 선택 항목을 읽을 수 있습니다")
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
