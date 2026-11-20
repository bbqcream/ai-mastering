# ai-mastering

무료 로컬 AI로 자동 믹싱하려면 Python 3.11 이상과 [Ollama](https://ollama.com/download)를 설치하고 아래 명령을 실행하세요. 기본 모델은 로컬 `qwen3:8b`입니다. 모델을 내려받은 뒤에는 계정이나 API 키 없이 PC에서 추론합니다. 모델 파일은 약 5.2GB이며 실행 중 추가 메모리를 사용합니다. 처리 속도와 판단 품질은 PC와 모델에 따라 달라집니다.

```powershell
python -m pip install -r requirements-ai.txt
ollama pull qwen3:8b
python ai_mix.py stems --output-dir ai-result
```

`ai_mix.py`는 트랙명, 라우드니스, 대역별 에너지, 다이내믹을 모델에 전달해 악기 분류와 게인·팬·EQ·컴프레션을 결정합니다. 전체 믹스를 렌더하고 다시 측정한 값을 모델에 전달해 기본 두 차례 수정한 다음 `ai-result/master.wav`를 저장합니다. 각 회차는 원본 스템에 절대 파라미터를 적용하므로 처리할 때마다 이펙트가 누적되는 것을 피합니다. 판단 근거, 적용값, 측정치는 `report.json`에 저장합니다. 출력 폴더는 새 이름을 지정해야 합니다.

```powershell
python ai_mix.py stems --passes 3 --model qwen3:8b --output-dir ai-result-2
```

Ableton에서 직접 자동 믹싱하려면 아래의 Ableton MCP Extended Remote Script 설정을 먼저 완료하고 uv를 설치하세요. 이어서 표시값 지원을 한 번 설치하고 Live를 재시작하세요. 설치 도구는 원본 Remote Script를 `.ai-mix-backup` 파일로 보관합니다. Remote Script를 업데이트한 뒤에도 이 명령을 다시 실행할 수 있습니다.

```powershell
python install_live_support.py
```

다른 위치에 Remote Script가 설치되어 있다면 `--script` 뒤에 해당 `AbletonMCP/__init__.py` 경로를 지정하세요. 작업할 세트를 Arrangement 모드로 열고 Loop와 Solo를 해제한 뒤 실행하세요.

```powershell
python auto_live.py --output-dir live-result
```

이 명령은 MCP 서버를 시작하고 활성 트랙을 읽습니다. 이름에서 악기를 분류하고 트랙별 라우드니스, 대역별 에너지, 크레스트 팩터, 스테레오 상관도, DC 오프셋을 측정합니다. AI는 악기별 출발점과 측정치를 참고해 페이더·팬과 내장 이펙트를 조절합니다. 분류가 불확실하면 디바이스와 측정치를 보고 역할을 다시 지정할 수 있습니다.

킥·베이스와 리드 보컬·반주의 세부 주파수 에너지도 비교합니다. 비슷한 음량으로 겹치는 대역을 AI에 후보로 전달해, 근음을 보존하면서 반주의 해당 대역을 조금 줄이는 판단에 참고하도록 합니다. 이 결과는 솔로 캡처의 평균 스펙트럼을 비교한 잠재적 충돌 정보이며, 실제 동시 발음과 청감은 믹스 재측정에서 함께 살펴야 합니다.

`prepare_track` 도구는 브라우저에서 EQ Eight와 필요한 Compressor를 찾아 기존 이펙트를 재사용하거나 로드하고, 실제 파라미터를 AI에 전달합니다. 이름을 바꾼 내장 디바이스도 클래스명으로 찾아 중복 로드를 막습니다. 필요하면 Glue Compressor, Utility, Limiter, Reverb, Delay도 사용할 수 있습니다. 연속형 노브는 `set_effect_value` 도구로 Hz·ms·dB·비율·퍼센트 목표를 지정합니다. 해당 트랙 출력을 잠시 차단하고 Live 표시값을 읽어 비선형 노브 위치를 계산한 다음, 목표값과 복구된 페이더를 확인합니다. 표시값 지원이 없거나 단위가 다르면 매핑을 중단합니다.

숫자 변경은 같은 구간에서 전후 오디오를 비교합니다. 신호 소실, 풀스케일 샘플 증가, 6 dB를 넘는 크레스트 감소, 큰 스테레오 상관도 악화, 킥·베이스 저역의 과도한 감소, 의도한 게인 이동 외의 12 LU 초과 감쇠를 감지하면 해당 설정을 이전 값으로 복구하고 다시 확인합니다. 이 기준은 기술적 손상을 줄이기 위한 보수적 휴리스틱입니다. `report.json`의 `change_review`에 승인·거부 사유와 측정치가 남습니다. 복구 대상은 숫자 파라미터와 페이더이며, 새로 로드한 이펙트는 체인에 남습니다.

필터 종류와 컷오프, 컴프레서 비율과 시간처럼 관련된 노브들은 `configure_effect`로 묶어 적용하고 결과를 함께 검증합니다. 묶음이 실패하면 구성 파라미터를 모두 복구합니다. 이 방식은 설정 도중의 임시 상태 때문에 유효한 조합을 거부하는 경우와 반복 재생 횟수를 줄입니다. 실시간 전후 캡처를 수행하므로 트랙 수와 변경 횟수에 따라 처리 시간이 늘어납니다.

수정 후에는 파라미터와 오디오를 다시 확인합니다. 트랙과 믹스의 재측정이 끝나면 전체 구간을 실시간 캡처해 `live-result/master.wav`로 마스터링하고 저장된 WAV를 다시 읽어 무음·라우드니스·트루피크를 검사합니다. `report.json`의 `quality`에 실제 파일 측정치와 목표 LUFS 달성 여부가 기록됩니다. 최종 마스터는 별도 WAV 파일로 저장됩니다. Live 세트 파일은 믹싱 후 직접 저장하세요.

보호 동작은 모델과 별도로 실행됩니다. 시작할 때 마스터 페이더를 최대 −12 dB로 낮춰 헤드룸을 확보합니다. 측정된 트랙·그룹 피크는 −3 dBFS, 마스터 피크는 −6 dBFS 이하를 목표로 감쇠하고 다시 측정합니다. 캡처 중 피크가 −0.18 dBFS 부근에 도달하면 재생을 멈추고 해당 캡처를 버립니다. 마스터를 6 dB 낮춰 최대 세 차례 캡처를 시도하고, 과부하가 반복되면 실패로 기록합니다. 이 감쇠는 Live 믹서에 남습니다. 짧은 피크를 놓칠 수 있는 미터와 소프트웨어 캡처를 이용하므로 반응 지연이 있으며, 원본이나 이전 이펙트에서 이미 발생한 왜곡은 별도 수정이 필요합니다.

오디오 캡처는 Windows의 기본 재생 장치 루프백을 사용합니다. Live 출력이 해당 장치로 들리도록 설정하고 다른 앱의 소리는 꺼두세요. ASIO 전용 출력은 WASAPI 루프백에 잡히지 않을 수 있어, 이 경우 공유 재생 장치나 루프백 경로를 한 번 설정해야 합니다. 무음 캡처는 보고서에 표시되며 최종 출력이 무음이면 작업을 실패로 기록합니다. 판단과 노브 매핑 중에는 재생을 멈추고, 캡처에 사용하는 솔로는 복구합니다. 성공하면 원래 재생 위치와 재생 상태를 복구하고 과부하로 중단되면 정지 상태를 유지합니다.

기본 분석은 곡의 앞·중간·뒤에서 각각 최대 16박을 골라 수행하며 짧은 곡은 겹치는 구간을 줄입니다. 최종 출력은 Arrangement 전체 길이입니다. `--start-beats 64 --end-beats 192`로 분석 및 출력 구간을 지정할 수 있습니다. `--loopback-device`로 재생 장치 ID를 지정할 수 있고, `--max-steps` 기본값은 120입니다. MCP 서버 명령을 바꾸려면 옵션 뒤 `--` 다음에 명령을 넣으세요.

MCP에서 Arrangement 클립 위치를 읽을 수 있으면 트랙별로 클립이 놓인 구간을 먼저 선택합니다. 선택한 구간은 변경 전후 비교에 동일하게 사용하고 `track_analysis_ranges`에 기록합니다. 스템 AI 경로도 처리 후 분석과 트랙 간 주파수 비교를 사용하며, 기술적 악화가 있는 트랙 수정과 전체 회차를 되돌려 마지막으로 유지한 설정을 출력합니다. 보고서의 `track_reviews`와 회차별 `accepted`에서 결과를 확인할 수 있습니다.

Live 수정 내역과 초기 믹서 상태는 `report.json`에 기록합니다. 실패 시 이미 적용된 믹스 수정은 세트에 남으며 보고서의 초기값과 도구별 변경 전후값으로 확인할 수 있습니다. 파라미터 범위 오류, 디바이스 정보 확인 누락, 미확인 이펙트 URI, 수정 후 재측정 누락은 차단합니다. 이 프로그램은 미리 학습된 로컬 모델을 사용하며, AI에는 측정된 수치가 전달됩니다.

검증은 합성 스템, 모의 Ollama 응답, 모의 Live 도구와 오디오 캡처로 수행했습니다. 실제 Ollama 모델의 음악적 판단, Ableton 기기 연결, WASAPI 오디오 경로는 실환경 검증이 필요합니다.

## Vocal Line 자동 튠과 Ableton 믹싱

`vocal-line`은 Vocal Line 피치 편집기입니다. 조성을 보컬에서 추정하거나 직접 선택해 자동 튠한 뒤, 음표별 편집을 거쳐 Ableton Live 보컬 트랙에 적용할 수 있습니다. 원본 듣기와 실행 취소도 지원합니다. 조성 추정은 단독 보컬의 음표에 근거하므로, 반주와 어긋나면 곡 조성을 직접 선택하세요.

Ableton VST3를 빌드하려면 Visual Studio의 C++ 빌드 도구와 CMake가 설치된 Windows에서 아래를 실행합니다.

```powershell
cd vocal-line
.\build-vst3.ps1
```

만들어진 `vocal-line\dist\VocalLine.vst3`를 VST3 폴더에 설치하고 Live에서 플러그인을 다시 검색하세요. 보컬 트랙에 Vocal Line을 넣고 **Transfer → 자동 튠 적용 → 음표 수정 → Live에 적용** 순서로 작업합니다. 한 Transfer 구간은 최대 30초입니다. 튠한 보컬을 반영한 뒤 자동 믹싱·마스터링은 이 문서의 `python auto_live.py --output-dir ...` 절차로 실행합니다.

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
