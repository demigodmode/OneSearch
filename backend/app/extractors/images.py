# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Image and RAW metadata extractor.
"""
import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from PIL import ExifTags, Image, UnidentifiedImageError

from ..config import settings
from ..schemas import Document
from ..services.app_settings import default_app_settings
from .base import BaseExtractor, extractor_registry
from .metadata import MetadataOnlyExtractor

_STANDARD_IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"]
_RAW_IMAGE_EXTENSIONS = [".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".dng"]
_EXIF_TAGS = {value: key for key, value in ExifTags.TAGS.items()}
_GPS_TAGS = ExifTags.GPSTAGS


class ImageExtractor(BaseExtractor):
    """Extract searchable metadata from images and best-effort RAW files."""

    SUPPORTED_EXTENSIONS = [*_STANDARD_IMAGE_EXTENSIONS, *_RAW_IMAGE_EXTENSIONS]
    MAX_FILE_SIZE = settings.max_office_file_size_mb * 1024 * 1024
    TIMEOUT = settings.office_extraction_timeout

    def __init__(
        self,
        source_id: str,
        source_name: str,
        index_gps_metadata: bool | None = None,
        image_metadata_max_size_mb: int | None = None,
        raw_metadata_mode: Literal["auto", "off"] | None = None,
    ):
        super().__init__(source_id, source_name)
        self.index_gps_metadata = index_gps_metadata
        self.image_metadata_max_size_mb = image_metadata_max_size_mb
        self.raw_metadata_mode = raw_metadata_mode

    def set_index_gps_metadata(self, enabled: bool) -> None:
        self.index_gps_metadata = enabled

    def set_image_metadata_max_size_mb(self, max_size_mb: int) -> None:
        self.image_metadata_max_size_mb = max_size_mb

    def set_raw_metadata_mode(self, mode: Literal["auto", "off"]) -> None:
        self.raw_metadata_mode = mode

    def extract(self, file_path: str) -> Document:
        path = Path(file_path)
        is_raw = path.suffix.lower() in _RAW_IMAGE_EXTENSIONS

        try:
            self._check_file_size_limit(file_path, self._image_metadata_max_size_bytes())
        except ValueError as e:
            return self._metadata_only_document(path, file_path, is_raw, str(e))

        metadata: dict[str, Any] = {}
        image_error: Exception | None = None
        try:
            metadata = self._extract_image_metadata(file_path)
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as e:
            image_error = e

        if is_raw and self._raw_metadata_enabled():
            try:
                raw_metadata = self._extract_raw_metadata_with_exiftool(file_path)
                metadata.update(raw_metadata)
            except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as raw_error:
                if not metadata:
                    return self._metadata_only_document(path, file_path, is_raw, str(raw_error) or str(image_error))
        elif image_error is not None:
            return self._metadata_only_document(path, file_path, is_raw, str(image_error))

        if not metadata:
            return self._metadata_only_document(path, file_path, is_raw, "No usable image metadata")

        doc = self._create_base_document(file_path, self._metadata_summary(path.name, metadata))
        doc.type = "raw_image" if is_raw else "image"
        doc.title = path.stem
        metadata["extraction_failed"] = False
        doc.metadata = metadata
        return doc

    def _extract_image_metadata(self, file_path: str) -> dict[str, Any]:
        with Image.open(file_path) as image:
            metadata: dict[str, Any] = {
                "width": image.width,
                "height": image.height,
                "image_format": image.format,
            }
            exif = image.getexif()
            if exif:
                self._add_exif_fields(metadata, exif)
                if self._gps_enabled():
                    gps = self._extract_gps(exif)
                    if gps:
                        metadata["gps"] = gps
            return metadata

    def _extract_raw_metadata_with_exiftool(self, file_path: str) -> dict[str, Any]:
        result = subprocess.run(
            ["exiftool", "-json", "-n", file_path],
            capture_output=True,
            text=True,
            timeout=settings.raw_metadata_timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "exiftool failed")
        payload = json.loads(result.stdout or "[]")
        if not payload:
            raise ValueError("exiftool returned no metadata")
        metadata = self._normalize_exiftool_metadata(payload[0])
        if not metadata:
            raise ValueError("exiftool returned no usable metadata")
        return metadata

    def _normalize_exiftool_metadata(self, raw: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        field_map = {
            "Make": "camera_make",
            "Model": "camera_model",
            "LensModel": "lens_model",
            "Lens": "lens_model",
            "ISO": "iso",
            "ImageWidth": "width",
            "ImageHeight": "height",
            "ExifImageWidth": "width",
            "ExifImageHeight": "height",
            "DateTimeOriginal": "date_taken",
            "CreateDate": "date_taken",
        }
        for raw_key, metadata_key in field_map.items():
            if raw_key in raw and raw[raw_key] not in (None, "") and metadata_key not in metadata:
                metadata[metadata_key] = _clean_value(raw[raw_key])

        if "FNumber" in raw and raw["FNumber"] not in (None, ""):
            metadata["aperture"] = f"f/{_format_decimal(_to_float(raw['FNumber']))}"
        if "ExposureTime" in raw and raw["ExposureTime"] not in (None, ""):
            metadata["exposure_time"] = _format_exposure(raw["ExposureTime"])
        if "FocalLength" in raw and raw["FocalLength"] not in (None, ""):
            metadata["focal_length"] = f"{_format_decimal(_to_float(raw['FocalLength']))}mm"
        if self._gps_enabled() and "GPSLatitude" in raw and "GPSLongitude" in raw:
            metadata["gps"] = {
                "latitude": _clean_value(raw["GPSLatitude"]),
                "longitude": _clean_value(raw["GPSLongitude"]),
            }
        return metadata

    def _add_exif_fields(self, metadata: dict[str, Any], exif: Image.Exif) -> None:
        field_map = {
            "Make": "camera_make",
            "Model": "camera_model",
            "DateTime": "date_taken",
            "DateTimeOriginal": "date_taken",
            "ISOSpeedRatings": "iso",
            "PhotographicSensitivity": "iso",
            "LensModel": "lens_model",
        }
        for tag_name, metadata_key in field_map.items():
            tag_id = _EXIF_TAGS.get(tag_name)
            if tag_id in exif:
                metadata[metadata_key] = _clean_value(exif.get(tag_id))

        f_number = exif.get(_EXIF_TAGS.get("FNumber"))
        if f_number is not None:
            metadata["aperture"] = f"f/{_format_decimal(_to_float(f_number))}"

        exposure = exif.get(_EXIF_TAGS.get("ExposureTime"))
        if exposure is not None:
            metadata["exposure_time"] = _format_exposure(exposure)

        focal_length = exif.get(_EXIF_TAGS.get("FocalLength"))
        if focal_length is not None:
            metadata["focal_length"] = f"{_format_decimal(_to_float(focal_length))}mm"

        orientation = exif.get(_EXIF_TAGS.get("Orientation"))
        if orientation is not None:
            metadata["orientation"] = _clean_value(orientation)

    def _gps_enabled(self) -> bool:
        if self.index_gps_metadata is None:
            return default_app_settings().index_gps_metadata
        return self.index_gps_metadata

    def _raw_metadata_enabled(self) -> bool:
        mode = self.raw_metadata_mode or default_app_settings().raw_metadata_mode
        return mode == "auto"

    def _image_metadata_max_size_bytes(self) -> int:
        if self.image_metadata_max_size_mb is None:
            self.image_metadata_max_size_mb = default_app_settings().image_metadata_max_size_mb
        return self.image_metadata_max_size_mb * 1024 * 1024

    def _extract_gps(self, exif: Image.Exif) -> dict[str, Any]:
        gps_tag = _EXIF_TAGS.get("GPSInfo")
        gps_info = exif.get(gps_tag) if gps_tag in exif else None
        if not gps_info:
            return {}
        gps: dict[str, Any] = {}
        if isinstance(gps_info, dict):
            for raw_key, value in gps_info.items():
                key = _GPS_TAGS.get(raw_key, str(raw_key))
                gps[key] = _clean_value(value)
        else:
            gps["raw"] = _clean_value(gps_info)
        return gps

    def _metadata_only_document(self, path: Path, file_path: str, is_raw: bool, error: str) -> Document:
        doc = MetadataOnlyExtractor(self.source_id, self.source_name).extract(file_path)
        doc.type = "raw_image" if is_raw else "image"
        doc.title = path.stem
        doc.metadata.update({
            "metadata_only": True,
            "extraction_failed": True,
            "extraction_error": error,
        })
        return doc

    def _metadata_summary(self, basename: str, metadata: dict[str, Any]) -> str:
        lines = [basename]
        labels = {
            "camera_make": "Camera make",
            "camera_model": "Camera model",
            "date_taken": "Date taken",
            "lens_model": "Lens",
            "iso": "ISO",
            "aperture": "Aperture",
            "exposure_time": "Exposure",
            "focal_length": "Focal length",
            "orientation": "Orientation",
        }
        for key, label in labels.items():
            if key in metadata:
                lines.append(f"{label}: {metadata[key]}")
        if "width" in metadata and "height" in metadata:
            lines.append(f"Dimensions: {metadata['width']}x{metadata['height']}")
        if "gps" in metadata:
            lines.append(f"GPS: {metadata['gps']}")
        return "\n".join(lines)


def _to_float(value: Any) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        return float(numerator) / float(denominator)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(Fraction(value))


def _format_decimal(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_exposure(value: Any) -> str:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        return f"{numerator}/{denominator}" if numerator == 1 else _format_decimal(numerator / denominator)
    as_float = _to_float(value)
    if 0 < as_float < 1:
        denominator = round(1 / as_float)
        return f"1/{denominator}"
    return _format_decimal(as_float)


def _clean_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00")
    if isinstance(value, tuple):
        return tuple(_clean_value(item) for item in value)
    return value


extractor_registry.register(ImageExtractor)
