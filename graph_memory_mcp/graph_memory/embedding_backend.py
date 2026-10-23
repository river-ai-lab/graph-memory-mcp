"""Local embedding backends.

``onnx`` (default) loads the fp32 ``onnx/model.onnx`` file from the Hugging Face
model repo and runs it with ONNX Runtime. Quantized ONNX files are never
selected. ``torch`` uses sentence-transformers and is an optional extra.
"""

from __future__ import annotations

import json
import threading
from typing import Protocol

import numpy as np

_ONNX_WEIGHTS = "onnx/model.onnx"
_TORCH_INSTALL = "uv sync --extra torch"
_LOAD_LOCK = threading.Lock()
# One loaded model per process. The fp32 weights are about 1.1 GB.
_LOADED: dict[tuple[str, str], EmbeddingBackend] = {}


class EmbeddingBackend(Protocol):
    """Encode texts into float32 vectors of shape ``(n, dimension)``."""

    dimension: int

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return one vector per text. Vectors are not required to be normalized."""


def load_embedding_backend(backend: str, model_name: str) -> EmbeddingBackend:
    """Build the requested backend. ``backend`` is ``onnx`` or ``torch``.

    A process keeps one instance per backend and model id. Loading the fp32
    weights again would duplicate a gigabyte-scale session.
    """
    name = (backend or "onnx").strip().lower()
    if name not in ("onnx", "torch"):
        raise ValueError(
            f"Unknown EMBEDDING_BACKEND {backend!r}. Expected 'onnx' or 'torch'."
        )
    key = (name, model_name)
    with _LOAD_LOCK:
        cached = _LOADED.get(key)
        if cached is not None:
            return cached
        if name == "onnx":
            loaded: EmbeddingBackend = OnnxEmbeddingBackend(model_name)
        else:
            loaded = TorchEmbeddingBackend(model_name)
        _LOADED[key] = loaded
        return loaded


class OnnxEmbeddingBackend:
    """fp32 ONNX Runtime backend with the model's sentence-transformers pooling."""

    def __init__(self, model_name: str):
        ort = _import_onnxruntime()
        self.model_name = model_name
        self._tokenizer = _load_tokenizer(model_name)
        self._pooling = _load_pooling(model_name)
        model_path = _download_required(model_name, _ONNX_WEIGHTS)
        self._session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._inputs = list(self._session.get_inputs())
        hidden = self._pooling.get("word_embedding_dimension")
        self.dimension = int(hidden) if hidden else 0

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            width = self.dimension or 0
            return np.zeros((0, width), dtype=np.float32)
        encoded = self._tokenizer.encode_batch(list(texts))
        input_ids = np.asarray([item.ids for item in encoded])
        attention_mask = np.asarray([item.attention_mask for item in encoded])
        feed: dict[str, np.ndarray] = {}
        for spec in self._inputs:
            id_type = _ort_int_dtype(spec.type)
            if spec.name == "input_ids":
                feed[spec.name] = input_ids.astype(id_type, copy=False)
            elif spec.name == "attention_mask":
                feed[spec.name] = attention_mask.astype(id_type, copy=False)
            elif spec.name == "token_type_ids":
                feed[spec.name] = np.zeros_like(input_ids, dtype=id_type)
            else:
                raise RuntimeError(
                    f"ONNX model {self.model_name} has unsupported input {spec.name!r}"
                )
        rows = _forward(self._session, feed, attention_mask, self._pooling)
        if self.dimension <= 0 and rows.ndim == 2 and rows.shape[1]:
            self.dimension = int(rows.shape[1])
        return rows


class TorchEmbeddingBackend:
    """sentence-transformers backend. Requires the ``torch`` extra."""

    def __init__(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDING_BACKEND=torch requires sentence-transformers and torch. "
                f"Install the optional extra: {_TORCH_INSTALL}"
            ) from exc
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        raw = self._model.encode(
            list(texts), convert_to_numpy=True, show_progress_bar=False
        )
        rows = np.asarray(raw, dtype=np.float32)
        if rows.ndim == 1:
            rows = rows.reshape(1, -1)
        return rows


def _import_onnxruntime():
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "ONNX embedding backend requires onnxruntime. "
            "Install project dependencies with: uv sync"
        ) from exc
    return ort


def _download_required(repo_id: str, filename: str) -> str:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError, LocalEntryNotFoundError

    try:
        return hf_hub_download(repo_id=repo_id, filename=filename)
    except (EntryNotFoundError, LocalEntryNotFoundError) as exc:
        if filename == _ONNX_WEIGHTS:
            raise RuntimeError(
                f"{repo_id} has no fp32 ONNX weights at {_ONNX_WEIGHTS}. "
                "Quantized ONNX files are not used. "
                "Set EMBEDDING_BACKEND=torch and install the optional extra: "
                f"{_TORCH_INSTALL}"
            ) from exc
        raise RuntimeError(f"Could not download {filename} from {repo_id}.") from exc


def _download_optional(repo_id: str, filename: str) -> str | None:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError, LocalEntryNotFoundError

    try:
        return hf_hub_download(repo_id=repo_id, filename=filename)
    except (EntryNotFoundError, LocalEntryNotFoundError):
        return None


def _load_json(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _load_pooling(repo_id: str) -> dict:
    path = _download_optional(repo_id, "1_Pooling/config.json")
    pooling = _load_json(path)
    if not pooling:
        return {
            "pooling_mode_cls_token": False,
            "pooling_mode_mean_tokens": True,
            "pooling_mode_max_tokens": False,
            "pooling_mode_mean_sqrt_len_tokens": False,
        }
    return pooling


def _load_tokenizer(repo_id: str):
    from tokenizers import Tokenizer

    path = _download_required(repo_id, "tokenizer.json")
    sbert = _load_json(_download_optional(repo_id, "sentence_bert_config.json"))
    max_length = int(sbert.get("max_seq_length") or 512)
    tokenizer = Tokenizer.from_file(path)
    tokenizer.enable_truncation(max_length=max_length)
    pad_id, pad_token = _pad_token(tokenizer, repo_id)
    tokenizer.enable_padding(pad_id=pad_id, pad_token=pad_token)
    return tokenizer


def _pad_token(tokenizer, repo_id: str) -> tuple[int, str]:
    for token in ("<pad>", "[PAD]"):
        pad_id = tokenizer.token_to_id(token)
        if pad_id is not None:
            return int(pad_id), token
    config = _load_json(_download_optional(repo_id, "config.json"))
    pad_id = int(config.get("pad_token_id") or 0)
    pad_token = tokenizer.id_to_token(pad_id) or "<pad>"
    return pad_id, pad_token


def _ort_int_dtype(ort_type: str):
    if "int32" in ort_type:
        return np.int32
    return np.int64


def _forward(session, feed: dict[str, np.ndarray], attention_mask, pooling: dict):
    outputs = session.run(None, feed)
    names = [item.name for item in session.get_outputs()]
    hidden = None
    for name, value in zip(names, outputs):
        array = np.asarray(value)
        if name == "last_hidden_state" and array.ndim == 3:
            hidden = array
            break
        if hidden is None and array.ndim == 3:
            hidden = array
    if hidden is None:
        array = np.asarray(outputs[0])
        if array.ndim == 2:
            return array.astype(np.float32, copy=False)
        raise RuntimeError(f"Unexpected ONNX output shape {array.shape}")
    return _pool(hidden, attention_mask, pooling)


def _pool(hidden: np.ndarray, attention_mask: np.ndarray, pooling: dict) -> np.ndarray:
    """Match sentence-transformers ``Pooling`` for mean and CLS."""
    if pooling.get("pooling_mode_max_tokens") or pooling.get(
        "pooling_mode_mean_sqrt_len_tokens"
    ):
        raise RuntimeError(
            "ONNX backend supports mean and CLS pooling. "
            f"Set EMBEDDING_BACKEND=torch for this pooling config ({pooling})."
        )
    use_cls = bool(pooling.get("pooling_mode_cls_token"))
    use_mean = bool(pooling.get("pooling_mode_mean_tokens", not use_cls))
    if not use_cls and not use_mean:
        raise RuntimeError(f"Pooling config enables no supported mode: {pooling}")
    hidden32 = hidden.astype(np.float32, copy=False)
    parts: list[np.ndarray] = []
    if use_cls:
        parts.append(hidden32[:, 0])
    if use_mean:
        mask = attention_mask.astype(np.float32)[..., None]
        summed = (hidden32 * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        parts.append(summed / counts)
    if len(parts) == 1:
        return parts[0]
    return np.concatenate(parts, axis=1)
