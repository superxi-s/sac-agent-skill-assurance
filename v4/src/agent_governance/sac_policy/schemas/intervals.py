from enum import Enum

POINTS_PER_DAY = 96

MINUTES_PER_INTERVAL = 15

class Decision(str, Enum):
    """每个 15 分钟点的最终决策。"""

    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"
