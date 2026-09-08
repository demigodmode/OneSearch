from types import SimpleNamespace

from app.services import extractor_config


class Fake:
    def __init__(self):
        self.values = {}

    def __getattr__(self, name):
        if name.startswith("set_"):
            return lambda value: self.values.__setitem__(name, value)
        raise AttributeError(name)


def settings():
    return {
        "unsupported_file_policy": "metadata_only",
        "index_gps_metadata": True,
        "max_text_file_size_mb": 1,
        "max_pdf_file_size_mb": 2,
        "max_office_file_size_mb": 3,
        "image_metadata_max_size_mb": 4,
        "raw_metadata_mode": "auto",
        "epub_extraction_max_size_mb": 5,
        "comic_extraction_max_size_mb": 6,
        "media_metadata_mode": "off",
        "media_probe_max_size_mb": 7,
    }


def test_configure_maps_every_setting_without_shared_mutation():
    first, second = Fake(), Fake()
    extractor_config.configure_extractor(first, settings())
    extractor_config.configure_extractor(second, SimpleNamespace(**settings()))
    assert first.values == second.values
    assert len(first.values) == 10


def test_choose_honors_unsupported_policy(monkeypatch):
    monkeypatch.setattr(extractor_config.extractor_registry, "get_extractor", lambda *args: None)
    assert (
        extractor_config.choose_extractor(
            "x.unknown", "s", "n", {**settings(), "unsupported_file_policy": "skip"}
        )
        is None
    )
    assert extractor_config.choose_extractor("x.unknown", "s", "n", settings()).source_id == "s"


def test_choose_configures_registered_extractor(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(extractor_config.extractor_registry, "get_extractor", lambda *args: fake)
    assert extractor_config.choose_extractor("x", "s", "n", settings()) is fake
    assert len(fake.values) == 10
