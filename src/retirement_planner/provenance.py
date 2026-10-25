"""Value-free fingerprints for resolved model inputs."""
import dataclasses
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import math


def scenario_fingerprint(scenario):
    def normalize(value):
        if dataclasses.is_dataclass(value):
            return normalize(dataclasses.asdict(value))
        if isinstance(value, dict):
            return {str(k.value if isinstance(k, Enum) else k): normalize(v) for k,v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value
    encoded = json.dumps(normalize(scenario),sort_keys=True,separators=(',', ':'),allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()
