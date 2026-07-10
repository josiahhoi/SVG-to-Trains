"""Allow `python -m svg2trains ...` as an alternative to the console script."""

import sys

from .cli import main

sys.exit(main())
