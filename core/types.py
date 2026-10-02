from dataclasses import dataclass, field


@dataclass
class Adjustment:
    """판단(suggest)이 만들고, 적용(render)이 받는 조정안.

    나중에 규칙 기반 -> LLM/학습 모델로 판단부를 바꿔도,
    에이블톤(AbletonOSC) 어댑터를 붙여도 이 형태는 그대로 쓴다.
    """

    track: str  # "master" 또는 트랙 이름
    effect: str  # highpass | eq_low_shelf | eq_peak | eq_high_shelf | compressor | limiter
    params: dict
    reason: str  # 사용자에게 보여줄 이유
    approved: bool = True


@dataclass
class Report:
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    adjustments: list = field(default_factory=list)
    info: dict = field(default_factory=dict)  # 렌더 중 생긴 부가 정보(게인 등)
