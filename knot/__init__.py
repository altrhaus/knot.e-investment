"""knot.e — 오케스트레이터 방식 자산관리 에이전트.

knot.e는 직접 백테스트/차트/크롤링을 하지 않는다. 이미 잘하는 도구들
(Claude API=정성 판단, 주가 API=정량 데이터, 텔레그램=알림)에게 일을 시키고
결과를 모아 윌리엄 프레임워크로 하나의 투자 판단을 만든다.
"""

__version__ = "0.1.0"

from .orchestrator import Orchestrator

__all__ = ["Orchestrator", "__version__"]
