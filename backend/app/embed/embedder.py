"""Embedder 实现。

全局约束：**单测不得下载/加载真实模型** —— 单测一律用 `HashingEmbedder`（确定性哈希袋向量），
真实 BGE-M3 只在显式打开环境变量时实例化，避免 CI 或普通 `pytest` 意外拉起 1GB+ 的 torch。
"""

import hashlib
import math
import os
import re

EMBEDDING_DIM = 1024
_TOKEN = re.compile(r"[a-zA-Z0-9]+|[一-鿿]")


class HashingEmbedder:
    """确定性哈希向量：同输入永远同向量，单位模长（余弦相似度即点积）。

    只用于单测与索引流程验证，**不具备语义能力**——真实检索质量必须靠 BGE-M3 集成用例评估。
    """

    dim = EMBEDDING_DIM

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            tokens = _TOKEN.findall(text or "")
            for i, tok in enumerate(tokens):
                grams = [tok]
                if i + 1 < len(tokens):
                    grams.append(f"{tok}|{tokens[i + 1]}")   # 相邻 bigram 给词序一点信号
                for gram in grams:
                    idx = int.from_bytes(
                        hashlib.blake2b(gram.encode("utf-8"), digest_size=4).digest(), "big"
                    ) % self.dim
                    vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class BgeM3Embedder:
    """真实 BAAI/bge-m3（1024 维）。仅在 `ZY_ALLOW_INTEGRATION=1` 时可用。"""

    dim = EMBEDDING_DIM

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        if os.getenv("ZY_ALLOW_INTEGRATION") != "1":
            raise RuntimeError(
                "BgeM3Embedder 会下载模型，单测禁用。集成用例请设 ZY_ALLOW_INTEGRATION=1")
        from sentence_transformers import SentenceTransformer   # 延迟导入，避免拖慢单测

        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [[float(x) for x in row] for row in vectors]
