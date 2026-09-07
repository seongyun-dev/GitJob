"""Optional PaddleOCR adapter used for image-only JobKorea postings."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse


class OcrUnavailableError(RuntimeError):
    """PaddleOCR is not installed in the current runtime."""


class OcrRecognitionError(RuntimeError):
    """PaddleOCR could not process one downloaded image."""


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float | None = None
    bbox: tuple[float, ...] = ()


@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: tuple[OcrLine, ...]
    average_confidence: float | None


class PaddleOcrEngine:
    """Load one Korean PaddleOCR engine and reuse it across all images."""

    def __init__(
        self,
        *,
        device: str = "cpu",
        language: str = "korean",
        min_confidence: float = 0.35,
    ) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as error:  # pragma: no cover - depends on local extras
            raise OcrUnavailableError(
                "PaddleOCR is not installed; install AI/requirements-ocr.txt"
            ) from error

        self.device = device
        self.language = language
        self.min_confidence = min_confidence
        try:
            self._engine = _create_engine(PaddleOCR, device, language)
        except Exception as error:  # pragma: no cover - backend-dependent setup
            raise OcrUnavailableError(
                "PaddleOCR could not be initialized; check PaddlePaddle and "
                f"the '{device}' device configuration ({type(error).__name__}: {error})"
            ) from error

    def recognize_bytes(self, image_bytes: bytes, *, suffix: str = ".jpg") -> OcrResult:
        if not image_bytes:
            raise OcrRecognitionError("downloaded image was empty")
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(image_bytes)
                temporary_path = Path(handle.name)
            raw_result = self._predict(temporary_path)
            lines = tuple(_extract_lines(raw_result, self.min_confidence))
            lines = tuple(
                sorted(
                    enumerate(lines),
                    key=lambda item: (_bbox_key(item[1].bbox), item[0]),
                )
            )
            ordered_lines = tuple(item[1] for item in lines)
            scores = [
                line.confidence for line in ordered_lines if line.confidence is not None
            ]
            return OcrResult(
                text="\n".join(line.text for line in ordered_lines),
                lines=ordered_lines,
                average_confidence=(sum(scores) / len(scores) if scores else None),
            )
        except OcrRecognitionError:
            raise
        except Exception as error:  # pragma: no cover - backend-dependent errors
            raise OcrRecognitionError(
                f"PaddleOCR inference failed: {type(error).__name__}: {error}"
            ) from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _predict(self, image_path: Path) -> Any:
        predict = getattr(self._engine, "predict", None)
        if callable(predict):
            return list(predict(str(image_path)))
        legacy_ocr = getattr(self._engine, "ocr", None)
        if callable(legacy_ocr):
            return legacy_ocr(str(image_path), cls=True)
        raise OcrRecognitionError("unsupported PaddleOCR API: predict/ocr not found")


def _create_engine(paddle_ocr: Any, device: str, language: str) -> Any:
    """Support the current 3.x constructor and the older 2.x fallback."""

    try:
        return paddle_ocr(
            lang=language,
            device=device,
            engine="paddle",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except TypeError:
        return paddle_ocr(
            lang=language,
            use_angle_cls=True,
            use_gpu=device != "cpu",
        )


def _extract_lines(result: Any, min_confidence: float) -> Iterable[OcrLine]:
    if isinstance(result, (list, tuple)):
        if _is_legacy_line(result):
            line = _extract_legacy_line(result, min_confidence)
            if line is not None:
                yield line
            return
        for item in result:
            yield from _extract_lines(item, min_confidence)
        return
    payload = _normalise_result_payload(result)
    if payload is not None:
        yield from _extract_mapping_lines(payload, min_confidence)


def _normalise_result_payload(result: Any) -> Mapping[str, Any] | None:
    if isinstance(result, Mapping):
        return result
    if isinstance(result, (list, tuple)):
        return None
    for attribute in ("json", "to_json"):
        value = getattr(result, attribute, None)
        if callable(value):
            value = value()
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                continue
        if isinstance(value, Mapping):
            return value
    texts = getattr(result, "rec_texts", None)
    if texts is not None:
        return {
            "rec_texts": texts,
            "rec_scores": getattr(result, "rec_scores", None),
            "rec_boxes": getattr(result, "rec_boxes", None),
        }
    return None


def _extract_mapping_lines(
    payload: Mapping[str, Any],
    min_confidence: float,
) -> Iterable[OcrLine]:
    nested = payload.get("res")
    if isinstance(nested, Mapping):
        yield from _extract_mapping_lines(nested, min_confidence)
        return

    texts = _as_items(_first_present(payload, "rec_texts", "texts"))
    if not texts:
        return
    scores = _as_items(_first_present(payload, "rec_scores", "scores"))
    boxes = _as_items(_first_present(payload, "rec_boxes", "rec_polys", "dt_polys"))
    for index, value in enumerate(texts):
        text = _clean_ocr_text(value)
        if not text:
            continue
        score = _number_at(scores, index)
        if score is not None and score < min_confidence:
            continue
        yield OcrLine(text=text, confidence=score, bbox=_bbox_at(boxes, index))


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _as_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            normalized = tolist()
        except (TypeError, ValueError):
            return ()
        if isinstance(normalized, (list, tuple)):
            return tuple(normalized)
    return ()


def _extract_legacy_lines(result: Any, min_confidence: float) -> Iterable[OcrLine]:
    """Parse PaddleOCR 2.x's ``[[box, (text, score)], ...]`` result shape."""

    if not isinstance(result, (list, tuple)):
        return
    for value in result:
        if _is_legacy_line(value):
            line = _extract_legacy_line(value, min_confidence)
            if line is not None:
                yield line
        else:
            yield from _extract_legacy_lines(value, min_confidence)


def _extract_legacy_line(value: Any, min_confidence: float) -> OcrLine | None:
    if not _is_legacy_line(value):
        return None
    bbox, recognised = value[0], value[1]
    text = _clean_ocr_text(recognised[0])
    score = _to_float(recognised[1]) if len(recognised) > 1 else None
    if not text or (score is not None and score < min_confidence):
        return None
    return OcrLine(text=text, confidence=score, bbox=_bbox(bbox))


def _is_legacy_line(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[1], (list, tuple))
        and bool(value[1])
        and isinstance(value[1][0], str)
    )


def _clean_ocr_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _number_at(values: Any, index: int) -> float | None:
    items = _as_items(values)
    if index >= len(items):
        return None
    return _to_float(items[index])


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bbox_at(values: Any, index: int) -> tuple[float, ...]:
    items = _as_items(values)
    if index >= len(items):
        return ()
    return _bbox(items[index])


def _bbox(value: Any) -> tuple[float, ...]:
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()
    if isinstance(value, (list, tuple)):
        flattened: list[float] = []
        for item in value:
            if isinstance(item, (list, tuple)):
                flattened.extend(_bbox(item))
            else:
                number = _to_float(item)
                if number is not None:
                    flattened.append(number)
        return tuple(flattened)
    return ()


def _bbox_key(bbox: tuple[float, ...]) -> tuple[float, float]:
    if len(bbox) >= 4:
        return bbox[1], bbox[0]
    return float("inf"), float("inf")


def image_suffix(image_url: str) -> str:
    suffix = Path(urlparse(image_url).path).suffix.lower()
    supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
    return suffix if suffix in supported else ".jpg"
