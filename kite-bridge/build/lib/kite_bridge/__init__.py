"""KiteBridge Universal App & File Runtime for KITE_OS (HP Folio 9480m)."""

from __future__ import annotations

__version__ = "0.1.0"

REQUIRED_DXVK_VERSION = "1.10.3"
MESA_DRIVER_PIN = "crocus"
LIBVA_DRIVER_PIN = "i965"

__all__ = [
    "__version__",
    "REQUIRED_DXVK_VERSION",
    "MESA_DRIVER_PIN",
    "LIBVA_DRIVER_PIN",
]
