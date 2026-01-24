"""Type aliases for semantic type safety.

Using NewType creates distinct types that catch bugs at type-check time
while having zero runtime overhead.

Example:
    def get_chunk(chunk_id: ChunkId) -> Chunk:
        ...
    
    # Type checker catches this mistake:
    file_id: FileId = FileId(123)
    get_chunk(file_id)  # Error: FileId is not ChunkId
"""

from __future__ import annotations

from typing import NewType, TypeVar, Dict, Any, List, Optional, Union

ChunkId = NewType("ChunkId", str)
FileId = NewType("FileId", str)
PointId = NewType("PointId", str)

LineNumber = NewType("LineNumber", int)
ByteOffset = NewType("ByteOffset", int)
ColumnNumber = NewType("ColumnNumber", int)

TokenCount = NewType("TokenCount", int)
CharCount = NewType("CharCount", int)

Score = NewType("Score", float)
Embedding = NewType("Embedding", List[float])

FilePath = NewType("FilePath", str)
RepoName = NewType("RepoName", str)
CollectionName = NewType("CollectionName", str)

Language = NewType("Language", str)
SymbolPath = NewType("SymbolPath", str)
SymbolName = NewType("SymbolName", str)

FileHash = NewType("FileHash", str)
ContentHash = NewType("ContentHash", str)

Payload = Dict[str, Any]
Metadata = Dict[str, Any]

T = TypeVar("T")
ChunkT = TypeVar("ChunkT", bound="Chunk")

__all__ = [
    "ChunkId",
    "FileId", 
    "PointId",
    "LineNumber",
    "ByteOffset",
    "ColumnNumber",
    "TokenCount",
    "CharCount",
    "Score",
    "Embedding",
    "FilePath",
    "RepoName",
    "CollectionName",
    "Language",
    "SymbolPath",
    "SymbolName",
    "FileHash",
    "ContentHash",
    "Payload",
    "Metadata",
    "T",
    "ChunkT",
]
