# ai-mastering (1단계: 마스터링 CLI)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python cli.py mix.wav --dry-run                  # 분석과 제안만
python cli.py mix.wav --ref ref.wav              # 조정안 확인 후 적용
python cli.py mix.wav --ref ref.wav --yes --ab   # 전부 적용 + 라우드니스 맞춘 비교 파일
```

구조: `core/master/analyze.py`(측정) -> `suggest.py`(조정안) -> `render.py`(적용).
`core/types.py`의 `Adjustment`가 판단과 적용 사이의 공통 형태예요.
