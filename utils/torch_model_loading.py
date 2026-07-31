"""Serialize native Torch model construction on Windows.

Loading two independent Torch/Transformers models at the same time has caused
native heap corruption in the desktop process.  Inference remains concurrent;
only the one-time model construction is guarded.
"""

from threading import RLock


torch_model_load_lock = RLock()
