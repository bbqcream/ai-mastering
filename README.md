# ai-mastering

스템 파일 이름에서 악기 역할을 찾고, 실제 오디오를 분석해 트랙마다 게인, 팬, 하이패스, EQ, 컴프레션을 정합니다. 믹스부터 최종 마스터 WAV까지 한 명령으로 실행할 수 있습니다. 분류와 처리에는 로컬 규칙과 오디오 측정을 사용합니다.

## Ableton 없이 자동 믹싱 및 마스터링

```powershell
python -m pip install -r requirements.txt
python mix_cli.py stems --master mastered.wav
```

`stems` 폴더에 시작점, 길이, 샘플레이트가 같은 WAV, AIFF, FLAC 스템을 넣으세요. 모노와 스테레오를 섞어서 사용할 수 있습니다. 출력은 스템 폴더 밖에 두세요.

- `01 킥.wav`, `808 Bass.wav`, `Lead Vox.wav`는 킥, 베이스, 리드 보컬로 분류하고 중앙에 둡니다.
- `BGV L.wav`, `HiHat.wav`, `GTR R.wav`는 백보컬, 하이햇, 기타로 분류합니다. 모노 트랙은 이름의 좌우 표기를 반영하거나 역할별로 번갈아 배치합니다. 스테레오 스템의 팬은 중앙에 둡니다.
- 역할별 목표 레벨과 측정된 라우드니스로 게인을 계산합니다. 역할별 대역 에너지가 두드러지면 EQ 컷을, 피크와 라우드니스 차이가 크면 해당 프로필에 따라 컴프레션을 적용합니다. 미분류·무음 스템은 개별 처리를 건너뜁니다.
- 합산한 믹스의 피크가 −6 dBFS를 넘으면 전체 게인을 낮춥니다. 마스터는 기본 −14 LUFS를 목표로 하며, 최종 트루피크 상한은 −1 dBTP입니다. 실제 수치는 실행 결과에 표시됩니다.

```powershell
python mix_cli.py stems --write-plan mix.json
python mix_cli.py stems --plan mix.json -o mix.wav --master mastered.wav
python mix_cli.py stems --master mastered.wav --lufs -12 --ceiling -1
python cli.py mix.wav --yes -o mastered.wav
```

`--write-plan`은 악기 분류, 측정치, 적용할 파라미터를 JSON에 저장합니다. `-o`는 프리마스터 믹스와 함께 확인할 때 사용하세요.

## Ableton Live에서 이름으로 믹서 자동 설정

[Ableton MCP Extended](https://github.com/staminna/ableton-mcp-extended)의 Remote Script와 MCP 서버가 필요합니다. 아래 설치 명령은 Python 3.11 이상과 uv가 설치된 환경에서 실행하세요. Live를 재시작하고 **Settings → Link, Tempo & MIDI → Control Surface**에서 `AbletonMCP`를 선택한 뒤 작업할 세트를 여세요.

```powershell
python -m pip install "mcp>=1.9,<2"
uvx --from git+https://github.com/staminna/ableton-mcp-extended.git ableton-mcp-extended-install-script
python live_mix.py --dry-run -- uvx --from git+https://github.com/staminna/ableton-mcp-extended.git ableton-mcp-extended
python live_mix.py -- uvx --from git+https://github.com/staminna/ableton-mcp-extended.git ableton-mcp-extended
```

Live 명령은 트랙 이름을 읽어 악기 역할별 절대 페이더 dB와 팬을 적용하고, 변경값을 다시 읽어 확인합니다. 그룹, 리턴, 마스터, 미분류 트랙과 −∞ 페이더는 건너뜁니다. 열린 세트에서 EQ·컴프레션까지 적용한 결과와 마스터 WAV가 필요하면, 마스터 이펙트를 빼고 정렬된 스템을 준비해 위 스템 명령을 사용하세요. 기존 `mix_cli.py stems --plan mix.json --ableton`은 AbletonOSC 팬 전송용입니다.
