"""Shared extractor selection and settings application for local and remote runs."""

from __future__ import annotations

from ..extractors import MetadataOnlyExtractor, extractor_registry

_SETTERS = (
    ("set_index_gps_metadata", "index_gps_metadata"),
    ("set_max_text_file_size_mb", "max_text_file_size_mb"),
    ("set_max_pdf_file_size_mb", "max_pdf_file_size_mb"),
    ("set_max_office_file_size_mb", "max_office_file_size_mb"),
    ("set_image_metadata_max_size_mb", "image_metadata_max_size_mb"),
    ("set_raw_metadata_mode", "raw_metadata_mode"),
    ("set_epub_extraction_max_size_mb", "epub_extraction_max_size_mb"),
    ("set_comic_extraction_max_size_mb", "comic_extraction_max_size_mb"),
    ("set_media_metadata_mode", "media_metadata_mode"),
    ("set_media_probe_max_size_mb", "media_probe_max_size_mb"),
)


def configure_extractor(extractor, settings):
    for setter, field in _SETTERS:
        if hasattr(extractor, setter):
            value = settings[field] if isinstance(settings, dict) else getattr(settings, field)
            getattr(extractor, setter)(value)
    return extractor


def choose_extractor(file_path, source_id, source_name, settings):
    extractor = extractor_registry.get_extractor(file_path, source_id, source_name)
    if extractor is None:
        policy = (
            settings["unsupported_file_policy"]
            if isinstance(settings, dict)
            else settings.unsupported_file_policy
        )
        if policy == "skip":
            return None
        extractor = MetadataOnlyExtractor(source_id, source_name)
    return configure_extractor(extractor, settings)
