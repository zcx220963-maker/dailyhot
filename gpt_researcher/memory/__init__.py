"""Memory module stub (vector store removed).

保持接口兼容：agent.py 用 Memory(cfg...) 初始化，但不再做向量存储。
所有方法均为 noop，避免 import 失败。
"""

# 兼容常量（embeddings.py 被删除后，context/compression.py 仍引用此常量）
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"


class Memory:
    """Noop Memory stub."""

    def __init__(self, *args, **kwargs):
        pass

    def add(self, *args, **kwargs):
        pass

    def get(self, *args, **kwargs):
        return []

    def clear(self, *args, **kwargs):
        pass

    def __contains__(self, item):
        return False

    def __len__(self):
        return 0
