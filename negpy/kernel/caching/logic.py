import functools
import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Optional, Any, Dict
from negpy.domain.types import ImageBuffer, ROI


@dataclass
class CacheEntry:
    """
    Intermediate pipeline stage result.
    """

    config_hash: str
    data: ImageBuffer
    metrics: Dict[str, Any]
    active_roi: Optional[ROI] = None


@functools.lru_cache(maxsize=64)
def _md5_of_serialized(serialized: str) -> str:
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


def calculate_config_hash(config: Any) -> str:
    """
    Stable hash of config state.

    Fast path: a hashable config (a frozen dataclass, a tuple) is keyed by the MD5 of its
    repr. Not hash(): it collides on values a slider reaches, hash(-1.0) == hash(-2.0).

    Fallback: configs with to_dict (e.g. WorkspaceConfig) or unhashable frozen
    dataclasses (lists/arrays in fields) go through JSON+MD5.
    """
    if not hasattr(config, "to_dict"):
        try:
            hash(config)
            return _md5_of_serialized(repr(config))
        except TypeError:
            pass

    if hasattr(config, "to_dict"):
        data = config.to_dict()
    else:
        data = asdict(config)

    serialized = json.dumps(data, sort_keys=True, default=str)
    return _md5_of_serialized(serialized)
