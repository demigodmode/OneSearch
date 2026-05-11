# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for image and RAW metadata extraction.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from PIL import Image

from app.extractors import ImageExtractor, extractor_registry


@pytest.fixture
def temp_dir():
    with TemporaryDirectory() as tmp:
        yield Path(tmp)


def write_jpeg_with_exif(path: Path) -> None:
    image = Image.new("RGB", (64, 32), color="red")
    exif = Image.Exif()
    exif[271] = "Canon"
    exif[272] = "EOS R6"
    exif[306] = "2024:08:12 18:43:00"
    exif[33434] = (1, 125)
    exif[33437] = (4, 1)
    exif[34855] = 800
    exif[37386] = (50, 1)
    exif[42036] = "RF24-105mm F4"
    image.save(path, exif=exif)


@pytest.mark.asyncio
async def test_extract_jpeg_exif_metadata_is_searchable(temp_dir):
    file_path = temp_dir / "IMG_1234.jpg"
    write_jpeg_with_exif(file_path)

    doc = await ImageExtractor("src", "Photos").extract_with_timeout(str(file_path))

    assert doc.type == "image"
    assert doc.title == "IMG_1234"
    assert doc.metadata["width"] == 64
    assert doc.metadata["height"] == 32
    assert doc.metadata["camera_make"] == "Canon"
    assert doc.metadata["camera_model"] == "EOS R6"
    assert doc.metadata["date_taken"] == "2024:08:12 18:43:00"
    assert doc.metadata["iso"] == 800
    assert doc.metadata["aperture"] == "f/4"
    assert doc.metadata["exposure_time"] == "1/125"
    assert doc.metadata["focal_length"] == "50mm"
    assert doc.metadata["lens_model"] == "RF24-105mm F4"
    assert doc.metadata["extraction_failed"] is False
    assert "Canon" in doc.content
    assert "EOS R6" in doc.content
    assert "ISO: 800" in doc.content
    assert "Aperture: f/4" in doc.content
    assert "Exposure: 1/125" in doc.content
    assert "RF24-105mm F4" in doc.content


@pytest.mark.asyncio
async def test_gps_metadata_is_excluded_by_default(temp_dir, monkeypatch):
    file_path = temp_dir / "gps.jpg"
    write_jpeg_with_exif(file_path)
    monkeypatch.setattr(ImageExtractor, "_extract_gps", lambda self, exif: {"GPSLatitudeRef": "N"})

    doc = await ImageExtractor("src", "Photos").extract_with_timeout(str(file_path))

    assert "gps" not in doc.metadata
    assert "GPS" not in doc.content


@pytest.mark.asyncio
async def test_gps_metadata_can_be_enabled(temp_dir, monkeypatch):
    file_path = temp_dir / "gps.jpg"
    write_jpeg_with_exif(file_path)
    monkeypatch.setattr(ImageExtractor, "_extract_gps", lambda self, exif: {"GPSLatitudeRef": "N"})

    doc = await ImageExtractor("src", "Photos", index_gps_metadata=True).extract_with_timeout(str(file_path))

    assert "gps" in doc.metadata
    assert "GPS" in doc.content


@pytest.mark.asyncio
async def test_raw_extension_falls_back_to_raw_image_metadata_only(temp_dir):
    file_path = temp_dir / "IMG_0001.CR3"
    file_path.write_bytes(b"fake raw data")

    doc = await ImageExtractor("src", "Photos").extract_with_timeout(str(file_path))

    assert doc.type == "raw_image"
    assert doc.title == "IMG_0001"
    assert doc.basename == "IMG_0001.CR3"
    assert doc.metadata["metadata_only"] is True
    assert doc.metadata["extraction_failed"] is True
    assert "IMG_0001.CR3" in doc.content


def test_image_and_raw_extensions_are_registered(temp_dir):
    for name in [
        "photo.jpg", "photo.jpeg", "photo.png", "photo.webp", "photo.gif", "photo.tif", "photo.tiff",
        "raw.cr2", "raw.cr3", "raw.nef", "raw.arw", "raw.raf", "raw.orf", "raw.rw2", "raw.dng",
    ]:
        assert ImageExtractor.supports_file(str(temp_dir / name)), name
        assert extractor_registry.get_extractor(str(temp_dir / name), "src", "Source") is not None
