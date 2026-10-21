"""Hydra's bounded development execution kernel."""

import sys

if sys.version_info < (3, 14):
    raise ImportError("Hydra requires Python 3.14 or newer. Select a Python 3.14+ environment.")

__version__ = "0.2.1"
