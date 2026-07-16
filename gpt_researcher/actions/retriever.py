"""Retriever factory and utilities for GPT Researcher.

仅保留免费搜索引擎：duckduckgo + searx。
"""


def get_retriever(retriever: str):
    """Get a retriever class by name."""
    match retriever:
        case "searx":
            from gpt_researcher.retrievers import SearxSearch
            return SearxSearch
        case "duckduckgo":
            from gpt_researcher.retrievers import Duckduckgo
            return Duckduckgo
        case _:
            # 默认回退到 duckduckgo
            from gpt_researcher.retrievers import Duckduckgo
            return Duckduckgo


def get_retrievers(headers: dict[str, str], cfg):
    """Determine which retriever(s) to use based on headers, config, or default."""
    if headers.get("retrievers"):
        retrievers = headers.get("retrievers").split(",")
    elif headers.get("retriever"):
        retrievers = [headers.get("retriever")]
    elif cfg.retrievers:
        if isinstance(cfg.retrievers, str):
            retrievers = cfg.retrievers.split(",")
        else:
            retrievers = cfg.retrievers
        retrievers = [r.strip() for r in retrievers]
    elif cfg.retriever:
        retrievers = [cfg.retriever]
    else:
        retrievers = [get_default_retriever().__name__]

    retriever_classes = [get_retriever(r) or get_default_retriever() for r in retrievers]
    return retriever_classes


def get_default_retriever():
    """Get the default retriever class (Duckduckgo)."""
    from gpt_researcher.retrievers import Duckduckgo
    return Duckduckgo
