"""Central registry for magic numbers used throughout the system.

Provides a single source of truth ensuring each trading method / strategy
has a unique, reproducible magic number. The numbers are generated at import
time using the dynamic `get_magic_number` helper from `magic_database`.
"""

from enum import Enum
from magic_database import get_magic_number

class MagicNumber(Enum):
    # Brain 1 (v1) method magic numbers – adjust brain identifier as needed
    SCALPING = get_magic_number(brain="v1", method="scalping")
    DAY_TRADING = get_magic_number(brain="v1", method="day_trading")
    SWING = get_magic_number(brain="v1", method="swing")
    POSITION = get_magic_number(brain="v1", method="position")
    TECHNICAL = get_magic_number(brain="v1", method="technical")
    FUNDAMENTAL = get_magic_number(brain="v1", method="fundamental")
    SENTIMENT = get_magic_number(brain="v1", method="sentiment")
    TREND = get_magic_number(brain="v1", method="trend")
    COUNTER_TREND = get_magic_number(brain="v1", method="counter_trend")
    BREAKOUT = get_magic_number(brain="v1", method="breakout")
    RANGE = get_magic_number(brain="v1", method="range")
    TMC = get_magic_number(brain="v1", method="tmc")
    # Brain identifiers – useful for backward‑compatibility constants
    BRAIN_V1 = get_magic_number(brain="v1", method="technical")  # placeholder method
    BRAIN_V2 = get_magic_number(brain="v2", method="technical")
    BRAIN_V3 = get_magic_number(brain="v3", method="technical")
    BRAIN_V4 = get_magic_number(brain="v4", method="technical")
    BRAIN_V5 = get_magic_number(brain="v5", method="technical")
    BRAIN_V6 = get_magic_number(brain="v6", method="technical")
    BRAIN_V7 = get_magic_number(brain="v7", method="technical")
    BRAIN_V8 = get_magic_number(brain="v8", method="technical")
    BRAIN_V9 = get_magic_number(brain="v9", method="technical")

# Helper to expose enum values as simple constants for legacy imports
MAGIC_SCALPING = MagicNumber.SCALPING.value
MAGIC_DAY_TRADING = MagicNumber.DAY_TRADING.value
MAGIC_SWING = MagicNumber.SWING.value
MAGIC_POSITION = MagicNumber.POSITION.value
MAGIC_TECHNICAL = MagicNumber.TECHNICAL.value
MAGIC_FUNDAMENTAL = MagicNumber.FUNDAMENTAL.value
MAGIC_SENTIMENT = MagicNumber.SENTIMENT.value
MAGIC_TREND = MagicNumber.TREND.value
MAGIC_COUNTER_TREND = MagicNumber.COUNTER_TREND.value
MAGIC_BREAKOUT = MagicNumber.BREAKOUT.value
MAGIC_RANGE = MagicNumber.RANGE.value
MAGIC_TMC = MagicNumber.TMC.value
MAGIC_BRAIN_V1 = MagicNumber.BRAIN_V1.value
MAGIC_BRAIN_V2 = MagicNumber.BRAIN_V2.value
MAGIC_BRAIN_V3 = MagicNumber.BRAIN_V3.value
MAGIC_BRAIN_V4 = MagicNumber.BRAIN_V4.value
MAGIC_BRAIN_V5 = MagicNumber.BRAIN_V5.value
MAGIC_BRAIN_V6 = MagicNumber.BRAIN_V6.value
MAGIC_BRAIN_V7 = MagicNumber.BRAIN_V7.value
MAGIC_BRAIN_V8 = MagicNumber.BRAIN_V8.value
MAGIC_BRAIN_V9 = MagicNumber.BRAIN_V9.value

# Optional default generic magic number – used where a specific method is not required.
MAGIC_NUMBER = MAGIC_TECHNICAL
