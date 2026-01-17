"""
Indexing commands.

Commands for indexing codebase and maintaining the vector database.
Re-exports index and prune commands from their respective modules.
"""

# Import index function from index.py
from scripts.ctx_cli.commands.index import index

# Import prune function from prune.py
from scripts.ctx_cli.commands.prune import prune

__all__ = ["index", "prune"]
