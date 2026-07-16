"""Vector store module stub (removed).

保持接口兼容：context/compression.py 引用 VectorStoreWrapper，
但实际不再做向量存储。所有方法均为 noop。
"""


class VectorStoreWrapper:
    """Noop vector store wrapper."""

    def __init__(self, *args, **kwargs):
        pass

    def add(self, *args, **kwargs):
        pass

    def search(self, *args, **kwargs):
        return []

    def delete(self, *args, **kwargs):
        pass

    def clear(self, *args, **kwargs):
        pass

    def __len__(self):
        return 0
