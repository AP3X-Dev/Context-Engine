"""
Entry point for running the CLI as a module.

Usage:
    python -m scripts.ctx_cli
    python -m scripts.ctx_cli --help
    python -m scripts.ctx_cli status
"""

import sys
from scripts.ctx_cli.main import main

if __name__ == "__main__":
    sys.exit(main())
