"""Small inspectable experiments in sampled event-triggered communication."""

from .engine import Config, Observation, compare, simulate
from .grid import GridSpec, grid_check
from .study import StudySpec, study

__version__ = "0.0.1"
__all__ = ["Config", "Observation", "StudySpec", "GridSpec", "compare", "simulate", "study", "grid_check", "__version__"]
