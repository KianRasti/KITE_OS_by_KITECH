"""Module entrypoint for `python -m kite_hw_tune`."""

import sys

from kite_hw_tune.cli import main_hw_tune

if __name__ == "__main__":
    sys.exit(main_hw_tune())
