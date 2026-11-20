"""Track-name recognition and conservative starting points for a mix."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    level: float  # LUFS offset from the measured stem median
    fader: float  # absolute dB starting point when only the Live name is available
    pan: float = 0.0
    highpass: float = 0.0
    eq_band: str = ""
    eq_freq: float = 0.0
    ratio: float = 1.0
    attack_ms: float = 20.0
    release_ms: float = 120.0


PROFILES = {
    "kick": Profile(1, -6, highpass=25, eq_band="low_mid", eq_freq=330, ratio=2.0),
    "snare": Profile(-1, -9, highpass=70, eq_band="low_mid", eq_freq=460, ratio=2.0),
    "hi_hat": Profile(-9, -16, 0.22, 145, "high", 8500),
    "cymbal": Profile(-8, -15, 0.32, 120, "high", 7600),
    "percussion": Profile(-5, -13, 0.25, 50),
    "drums": Profile(0, -7, highpass=25),
    "bass": Profile(0, -8, highpass=22, eq_band="low_mid", eq_freq=310, ratio=2.2, release_ms=150),
    "lead_vocal": Profile(3, -5, highpass=70, eq_band="low_mid", eq_freq=320, ratio=2.5, attack_ms=12),
    "backing_vocal": Profile(-6, -13, 0.35, 95, "low_mid", 340, 2.0, 12),
    "guitar": Profile(-4, -11, 0.3, 65, "low_mid", 300),
    "keys": Profile(-4, -11, 0.16, 40, "low_mid", 300),
    "lead_synth": Profile(-2, -9, highpass=55, eq_band="high_mid", eq_freq=3300),
    "pad": Profile(-8, -15, 0.2, 70, "low_mid", 330),
    "strings": Profile(-5, -12, 0.18, 55, "low_mid", 340),
    "winds": Profile(-4, -11, 0.18, 50),
    "fx": Profile(-10, -16, 0.18),
    "unknown": Profile(0, 0),
}

# Specific names take precedence over a family name, e.g. 808 Kick over 808.
ALIASES = (
    ("backing_vocal", "backing vocal|backing vocals|bg vocal|back vocal|bgv|bvox|bgvox|vocal double|vox double|adlib|ad lib|vocal harmony|vox harmony|백보컬|코러스|화음|애드립"),
    ("lead_vocal", "lead vocal|lead vox|main vocal|main vox|리드보컬|메인보컬|리드 보컬|메인 보컬"),
    ("kick", "kick|kick drum|bd|bass drum|킥|킥드럼|베이스 드럼"),
    ("snare", "snare|clap|rimshot|스네어|클랩|박수"),
    ("hi_hat", "hi hat|hi hats|hihat|hihats|hh|하이햇|하이햇트|하이 햇"),
    ("cymbal", "cymbal|cymbals|ride cymbal|crash|overhead|overheads|oh|심벌|심벌즈|크래시|라이드"),
    ("lead_vocal", "vocal|vocals|vox|voc|rap|보컬|랩"),
    ("bass", "bass|sub|subbass|808|bassline|베이스|서브베이스|서브 베이스"),
    ("percussion", "percussion|perc|tom|toms|shaker|conga|tambourine|탐|타악기|퍼커션|셰이커"),
    ("drums", "drum|drums|drumkit|드럼|드럼버스"),
    ("guitar", "guitar|guitars|gtr|gt|acoustic guitar|일렉기타|어쿠스틱기타|기타"),
    ("keys", "piano|keys|keyboards|keyboard|organ|rhodes|피아노|건반|오르간"),
    ("strings", "strings|violin|viola|cello|스트링|바이올린|첼로|현악기"),
    ("winds", "brass|sax|saxophone|trumpet|flute|woodwind|브라스|색소폰|트럼펫|플루트|관악기"),
    ("pad", "pad|pads|atmosphere|패드"),
    ("lead_synth", "lead synth|synth lead|synth|synthesizer|pluck|신스|신디|신스리드"),
    ("fx", "fx|sfx|riser|impact|transition|이펙트|효과음|라이저"),
)


def _tokens(name):
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name).casefold()
    # Live/stem labels often add sequence numbers directly next to the name.
    return " ".join(re.findall(r"[a-z]+|[0-9]+|[가-힣]+", name))


def classify_track(name):
    tokens = f" {_tokens(name)} "
    for role, aliases in ALIASES:
        if any(f" {alias} " in tokens for alias in aliases.split("|")):
            return role
    return "unknown"


def track_pan(name, profile, position):
    tokens = set(_tokens(name).split())
    if not profile.pan:
        return 0.0
    if tokens & {"l", "left", "왼쪽"}:
        return -profile.pan
    if tokens & {"r", "right", "오른쪽"}:
        return profile.pan
    return profile.pan * (-1 if position % 2 == 0 else 1)
