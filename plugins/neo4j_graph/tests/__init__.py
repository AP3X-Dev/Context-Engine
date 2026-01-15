# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Isolated tests for the Neo4j Graph plugin.

Run tests:
    cd plugins/neo4j_graph
    pip install -e ".[dev]"
    pytest tests/ -v -m "not neo4j"

Run with live Neo4j:
    NEO4J_PASSWORD=test pytest tests/ -v
"""

