"""涟漪情感系统 v3：连续动力状态、关系层、语调渲染和人格隔离。"""
from .manager import get_manager, EmotionManager
from .v3_models import AffectDelta, EmotionalStateV3

__all__ = ["get_manager", "EmotionManager", "AffectDelta", "EmotionalStateV3"]
