from app.services.remote_ingest import canonical_remote_path, remote_document_id


def test_remote_paths_are_canonical_and_ids_are_path_derived():
    assert canonical_remote_path("folder/file.txt") == "folder/file.txt"
    assert remote_document_id("source", "folder/file.txt") == remote_document_id(
        "source", "folder/file.txt"
    )
