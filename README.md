# ai-mastering (1단계: 마스터링 CLI)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python cli.py mix.wav --dry-run                  # 분석과 제안만
python cli.py mix.wav --ref ref.wav              # 조정안 확인 후 적용
python cli.py mix.wav --ref ref.wav --yes --ab   # 전부 적용 + 라우드니스 맞춘 비교 파일
python cli.py stems/ --yes -o mastered.wav       # 스템 합산 후 마스터링
python mix_cli.py stems/ --write-plan mix.json   # 스템별 초기 믹스안 생성
python mix_cli.py stems/ --plan mix.json -o mix.wav
python cli.py mix.wav --yes -o mastered.wav      # 믹스 파일 마스터링
python mix_cli.py stems/ --plan mix.json --ableton  # Live 트랙 팬 적용
```

구조: `core/master/analyze.py`(측정) -> `suggest.py`(조정안) -> `render.py`(적용).
`core/types.py`의 `Adjustment`가 판단과 적용 사이의 공통 형태예요.

## Ableton Live 믹싱/마스터링

1. Live에서 각 트랙을 같은 시작점과 같은 종료점으로 WAV 스템 내보내기
   (마스터 이펙트는 끄고, 모든 스템의 샘플레이트와 채널 수를 동일하게 유지).
2. `python mix_cli.py stems/ --write-plan mix.json`으로 스템별 라우드니스 분석과
   초기 게인 스테이징을 계산합니다. `mix.json`에서 각 트랙의 `gain_db`와
   `pan`(-1 왼쪽, 0 중앙, +1 오른쪽)을 원하는 값으로 조정할 수 있습니다.
3. `python mix_cli.py stems/ --plan mix.json -o mix.wav`로 스테레오 믹스를 만들고,
   `python cli.py mix.wav --yes -o mastered.wav`로 마스터링합니다.
4. AbletonOSC Remote Script는 `~/Music/Ableton/User Library/Remote Scripts/AbletonOSC`
   에 설치했습니다. Live 11 이상을 재시작한 뒤 `Preferences > Link, Tempo & MIDI`
   의 Control Surface 목록에서 `AbletonOSC`를 선택하세요. Live에
   `Listening for OSC on port 11000` 메시지가 보이면 연결 준비가 된 것입니다.
5. `mix.json`의 트랙 `name`은 Live 트랙 이름과 같아야 합니다(대소문자 무시).
   `python mix_cli.py stems/ --plan mix.json --ableton`으로 이름이 일치하는 트랙에
   팬 값을 전송할 수 있습니다. Live OSC 볼륨은 내부 파라미터 스케일이 dB와
   다르므로 이 단계에서는 팬만 전송하고 게인 조정은 렌더된 믹스에 반영합니다.

스템은 파일명 순으로 샘플 단위 합산합니다. 길이·샘플레이트·채널 수가 다르면
잘못 정렬된 믹스를 만들지 않도록 처리를 중단합니다. 초기 게인 제안은 스템 LUFS의
중앙값을 기준으로 한 규칙 기반 게인 스테이징이며, 창작적 밸런스 판단을 대신하지 않습니다.
