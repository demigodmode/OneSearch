import hashlib

from onesearch_agent.worker import batch_documents
from onesearch_shared import NormalizedRemoteDocument


def test_batches_are_bounded_and_deterministic():
    docs = [
        NormalizedRemoteDocument(source_id="s", path=f"{n}.txt", content="x" * 20, modified_at=1)
        for n in range(3)
    ]
    batches = list(batch_documents("job", docs, max_documents=2, max_bytes=300))

    assert [len(batch.documents) for batch in batches] == [2, 1]
    payload = batches[0].model_copy(update={"batch_id": "pending"}).model_dump_json()
    assert batches[0].batch_id == f"job:0:{hashlib.sha256(payload.encode()).hexdigest()}"
