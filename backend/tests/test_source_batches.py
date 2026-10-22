"""Durable source batch API contracts."""

from uuid import uuid4

from app.models import Source


def request_payload(*paths):
    return {
        "id": str(uuid4()),
        "location_type": "local",
        "common_settings": {"schedule_type": "cron", "scan_schedule": "@daily"},
        "items": [{"id": str(uuid4()), "name": f"Folder {index}", "root_path": path} for index, path in enumerate(paths)],
    }


def test_create_batch_replays_snapshot_and_rejects_changed_payload(client, temp_source_dir):
    payload = request_payload(temp_source_dir)
    created = client.post('/api/sources/batches', json=payload)
    assert created.status_code == 201, created.text
    assert created.json()['items'][0]['state'] == 'pending'
    assert client.post('/api/sources/batches', json=payload).json() == created.json()
    payload['items'][0]['name'] = 'Changed'
    assert client.post('/api/sources/batches', json=payload).status_code == 409


def test_created_item_replays_after_source_deletion(client, db_session, temp_source_dir):
    payload = request_payload(temp_source_dir)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    url = f"/api/sources/batches/{payload['id']}/items/{payload['items'][0]['id']}/create"
    created = client.post(url, json={})
    assert created.status_code == 200, created.text
    item = created.json()
    assert item['state'] == 'created'
    source = db_session.get(Source, item['source_id'])
    assert source and source.next_scan_at is not None
    db_session.delete(source)
    db_session.commit()
    replay = client.post(url, json={})
    assert replay.status_code == 200
    assert replay.json()['state'] == 'created'
    assert replay.json()['source_deleted'] is True


def test_batch_is_owner_scoped_including_uuid_collision(client, db_session, temp_source_dir):
    from app.api.auth import create_access_token, hash_password
    from app.models import User
    payload = request_payload(temp_source_dir)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    other = User(username='other-owner', password_hash=hash_password('password'), is_active=True)
    db_session.add(other)
    db_session.commit()
    token, _ = create_access_token(other.id, other.username)
    headers = {'Authorization': f'Bearer {token}'}
    item_url = f"/api/sources/batches/{payload['id']}/items/{payload['items'][0]['id']}/create"
    for method, url, body in [
        ('post', '/api/sources/batches', payload),
        ('get', f"/api/sources/batches/{payload['id']}", None),
        ('post', item_url, {}),
        ('post', f"/api/sources/batches/{payload['id']}/dismiss", {}),
    ]:
        response = getattr(client, method)(url, headers=headers, **({'json': body} if body is not None else {}))
        assert response.status_code == 404, response.text
    assert client.get('/api/sources/batches', headers=headers).json()['batches'] == []


def test_batch_partial_results_and_duplicate_selection(client, db_session, temp_source_dir):
    from pathlib import Path
    first = str(Path(temp_source_dir) / 'subdir')
    missing = str(Path(temp_source_dir) / 'missing')
    payload = request_payload(first, first + '/.', missing)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    results = []
    for item in payload['items']:
        response = client.post(f"/api/sources/batches/{payload['id']}/items/{item['id']}/create", json={})
        assert response.status_code == 200, response.text
        results.append(response.json())
    assert [result['state'] for result in results] == ['created', 'duplicate_selection', 'failed']
    assert results[1]['duplicate_of_item_id'] == payload['items'][0]['id']
    assert results[2]['error']
    Path(missing).mkdir()
    retried = client.post(f"/api/sources/batches/{payload['id']}/items/{payload['items'][2]['id']}/create", json={})
    assert retried.json()['state'] == 'created'
    assert db_session.query(Source).count() == 2


def test_existing_legacy_duplicates_choose_oldest_then_id(client, db_session, temp_source_dir):
    from datetime import datetime
    for source_id in ['z-source', 'a-source']:
        db_session.add(Source(id=source_id, name=source_id, root_path=temp_source_dir, created_at=datetime(2020, 1, 1)))
    db_session.commit()
    payload = request_payload(temp_source_dir)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    result = client.post(f"/api/sources/batches/{payload['id']}/items/{payload['items'][0]['id']}/create", json={})
    assert result.json()['state'] == 'already_exists'
    assert result.json()['source_id'] == 'a-source'
    assert db_session.query(Source).count() == 2


def test_batch_list_cursor_and_dismiss(client, temp_source_dir):
    ids = []
    for _ in range(3):
        payload = request_payload(temp_source_dir)
        ids.append(payload['id'])
        assert client.post('/api/sources/batches', json=payload).status_code == 201
    page = client.get('/api/sources/batches?limit=2').json()
    assert len(page['batches']) == 2 and page['next_cursor']
    later = client.get('/api/sources/batches', params={'limit': 2, 'cursor': page['next_cursor']}).json()
    assert len(later['batches']) == 1
    assert len({row['id'] for row in page['batches'] + later['batches']}) == 3
    assert client.get('/api/sources/batches?limit=21').status_code == 422
    assert client.post(f"/api/sources/batches/{ids[0]}/dismiss").json()['dismissed'] is True
    assert client.get(f"/api/sources/batches/{ids[0]}").status_code == 200


def test_remote_batch_requires_exact_fresh_proof_and_accepts_offline_agent(client, db_session):
    import json
    from datetime import datetime, timezone

    from app.models import Agent, AgentJob, AppSetting
    from app.services.agent_auth import hash_token
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agent = Agent(id='batch-agent', name='Batch agent', platform='linux', version='1', protocol_version=1,
                  token_hash=hash_token('credential'), allowed_roots=json.dumps([{'root_id': 'docs', 'path': '/srv/docs'}]),
                  status='offline', approved_at=now)
    proof = AgentJob(id=str(uuid4()), agent_id=agent.id, kind='browse', reason='validate', status='completed',
                     payload=json.dumps({'operation': 'validate', 'root_path': '/srv/docs/team'}), completed_at=now)
    db_session.add_all([agent, proof, AppSetting(key='remote_agents_enabled', value='true')])
    db_session.commit()
    payload = request_payload('/srv/docs/team')
    payload.update(location_type='agent', agent_id=agent.id)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    url = f"/api/sources/batches/{payload['id']}/items/{payload['items'][0]['id']}/create"
    missing = client.post(url, json={}).json()
    assert missing['state'] == 'failed'
    created = client.post(url, json={'path_validation_job_id': proof.id}).json()
    assert created['state'] == 'created'
    assert client.post(url, json={}).json()['source_id'] == created['source_id']


def test_remote_batch_rejects_outside_roots_and_mismatched_proof(client, db_session):
    import json
    from datetime import datetime, timezone

    from app.models import Agent, AgentJob, AppSetting
    from app.services.agent_auth import hash_token
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agent = Agent(id='batch-agent', name='Batch agent', platform='linux', version='1', protocol_version=1,
                  token_hash=hash_token('credential'), allowed_roots=json.dumps([{'root_id': 'docs', 'path': '/srv/docs'}]),
                  status='offline', approved_at=now)
    proof = AgentJob(id=str(uuid4()), agent_id=agent.id, kind='browse', reason='validate', status='completed',
                     payload=json.dumps({'operation': 'validate', 'root_path': '/srv/docs/other'}), completed_at=now)
    db_session.add_all([agent, proof, AppSetting(key='remote_agents_enabled', value='true')])
    db_session.commit()
    payload = request_payload('/srv/docs/team', '/outside')
    payload.update(location_type='agent', agent_id=agent.id)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    outcomes = [client.post(f"/api/sources/batches/{payload['id']}/items/{item['id']}/create", json={'path_validation_job_id': proof.id}).json() for item in payload['items']]
    assert [item['state'] for item in outcomes] == ['failed', 'failed']
    assert db_session.query(Source).count() == 0


def test_account_deletion_scrubs_batch_snapshots_and_keeps_identity(client, db_session, test_user, temp_source_dir):
    from app.models import SourceBatch, SourceBatchItem
    payload = request_payload(temp_source_dir)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    user = test_user['user']
    db_session.delete(user)
    db_session.commit()
    batch = db_session.get(SourceBatch, payload['id'])
    item = db_session.get(SourceBatchItem, (payload['id'], payload['items'][0]['id']))
    assert batch.request_snapshot == '{}'
    assert item.name == item.root_path == ''
    assert batch.id == payload['id'] and item.item_id == payload['items'][0]['id']


def test_concurrent_batches_at_same_location_create_one_source(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    from threading import Barrier

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.source_batches import _write_item
    from app.api.sources import _build_source
    from app.config import settings
    from app.models import Base, SourceBatch, SourceBatchItem
    from app.schemas import SourceCreate
    database = create_engine(f'sqlite:///{tmp_path / "batches.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(database)
    sessions = sessionmaker(bind=database, autoflush=False)
    folder = tmp_path / 'docs'
    folder.mkdir()
    original_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(tmp_path)
    try:
        ids = [str(uuid4()), str(uuid4())]
        item_ids = [str(uuid4()), str(uuid4())]
        with sessions() as session:
            for batch_id, item_id in zip(ids, item_ids, strict=True):
                batch = SourceBatch(id=batch_id, owner_user_id=1, fingerprint='fingerprint',
                    request_snapshot='{"common_settings":{}}', location_type='local', created_at=datetime.now(timezone.utc).replace(tzinfo=None), updated_at=datetime.now(timezone.utc).replace(tzinfo=None))
                batch.items = [SourceBatchItem(batch_id=batch_id, item_id=item_id, position=0, name='Docs', root_path=str(folder))]
                session.add(batch)
            session.commit()
        barrier = Barrier(2)
        def run(index):
            with sessions() as session:
                source = _build_source(session, SourceCreate(id=f'batch-{index}', name='Docs', root_path=str(folder)), f'batch-{index}', str(folder))
                barrier.wait()
                return _write_item(session, ids[index], item_ids[index], 1, source, None, None)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        assert {row['state'] for row in results} == {'created', 'already_exists'}
        with sessions() as session:
            assert session.query(Source).count() == 1
    finally:
        settings.allowed_source_paths = original_allowed
        database.dispose()


def test_busy_writer_returns_bounded_503_without_changing_item(tmp_path):
    import time
    from datetime import datetime, timezone

    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.source_batches import _write_item
    from app.api.sources import _build_source
    from app.config import settings
    from app.models import Base, SourceBatch, SourceBatchItem
    from app.schemas import SourceCreate
    engine = create_engine(f'sqlite:///{tmp_path / "busy.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    folder = tmp_path / 'docs'
    folder.mkdir()
    batch_id, item_id = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with sessions() as session:
        session.add(SourceBatch(id=batch_id, owner_user_id=1, fingerprint='f', request_snapshot='{"common_settings":{}}',
            location_type='local', created_at=now, updated_at=now,
            items=[SourceBatchItem(batch_id=batch_id, item_id=item_id, position=0, name='Docs', root_path=str(folder))]))
        session.commit()
    old_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(tmp_path)
    blocker = engine.connect()
    try:
        blocker.exec_driver_sql('BEGIN IMMEDIATE')
        with sessions() as session:
            source = _build_source(session, SourceCreate(id='batch-busy', name='Docs', root_path=str(folder)), 'batch-busy', str(folder))
            start = time.monotonic()
            with __import__('pytest').raises(HTTPException) as error:
                _write_item(session, batch_id, item_id, 1, source, None, None)
            assert error.value.status_code == 503
            assert time.monotonic() - start < 2.5
    finally:
        blocker.rollback()
        blocker.close()
        settings.allowed_source_paths = old_allowed
    with sessions() as session:
        assert session.get(SourceBatchItem, (batch_id, item_id)).state == 'pending'
        assert session.query(Source).count() == 0
    engine.dispose()


def test_item_source_and_outcome_roll_back_together(tmp_path):
    from datetime import datetime, timezone

    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.source_batches import _write_item
    from app.api.sources import _build_source
    from app.config import settings
    from app.models import Base, SourceBatch, SourceBatchItem
    from app.schemas import SourceCreate
    engine = create_engine(f'sqlite:///{tmp_path / "atomic.db"}')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    folder = tmp_path / 'docs'
    folder.mkdir()
    batch_id, item_id = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with sessions() as session:
        session.add(SourceBatch(id=batch_id, owner_user_id=1, fingerprint='f', request_snapshot='{"common_settings":{}}',
            location_type='local', created_at=now, updated_at=now,
            items=[SourceBatchItem(batch_id=batch_id, item_id=item_id, position=0, name='Docs', root_path=str(folder))]))
        session.commit()
    old_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(tmp_path)
    try:
        with sessions() as session:
            source = _build_source(session, SourceCreate(id='batch-atomic', name='Docs', root_path=str(folder)), 'batch-atomic', str(folder))
            def crash(): raise RuntimeError('simulated failure before commit')
            session.flush = crash
            with pytest.raises(RuntimeError, match='simulated failure'):
                _write_item(session, batch_id, item_id, 1, source, None, None)
        with sessions() as session:
            assert session.get(SourceBatchItem, (batch_id, item_id)).state == 'pending'
            assert session.query(Source).count() == 0
    finally:
        settings.allowed_source_paths = old_allowed
        engine.dispose()



def test_batch_raw_body_limit_rejects_whitespace_heavy_request(client, temp_source_dir):
    import json
    payload = request_payload(temp_source_dir)
    raw = json.dumps(payload) + (' ' * 65_536)
    response = client.post('/api/sources/batches', content=raw, headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    assert client.get(f"/api/sources/batches/{payload['id']}").status_code == 404


def test_duplicate_remote_canonical_paths_link_to_first_item_after_retry(client, db_session):
    import json
    from datetime import datetime, timezone

    from app.models import Agent, AgentJob, AppSetting
    from app.services.agent_auth import hash_token
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agent = Agent(id='batch-agent', name='Batch agent', platform='linux', version='1', protocol_version=1,
                  token_hash=hash_token('credential'), allowed_roots=json.dumps([{'root_id': 'docs', 'path': '/srv/docs'}]),
                  status='offline', approved_at=now)
    proof = AgentJob(id=str(uuid4()), agent_id=agent.id, kind='browse', reason='validate', status='completed',
                     payload=json.dumps({'operation': 'validate', 'root_path': '/srv/docs/team'}), completed_at=now)
    db_session.add_all([agent, proof, AppSetting(key='remote_agents_enabled', value='true')])
    db_session.commit()
    payload = request_payload('/srv/docs/./team', '/srv/docs/team')
    payload.update(location_type='agent', agent_id=agent.id)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    urls = [f"/api/sources/batches/{payload['id']}/items/{item['id']}/create" for item in payload['items']]
    assert client.post(urls[0], json={}).json()['state'] == 'failed'
    duplicate = client.post(urls[1], json={'path_validation_job_id': proof.id}).json()
    assert duplicate['state'] == 'duplicate_selection'
    assert duplicate['duplicate_of_item_id'] == payload['items'][0]['id']
    assert duplicate['source_id'] is None
    first = client.post(urls[0], json={'path_validation_job_id': proof.id}).json()
    assert first['state'] == 'created'
    recovered = client.get(f"/api/sources/batches/{payload['id']}").json()['items'][1]
    assert recovered['source_id'] == first['source_id']


def test_same_item_concurrent_calls_return_one_created_source(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    from threading import Barrier

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.source_batches import _write_item
    from app.api.sources import _build_source
    from app.config import settings
    from app.models import Base, SourceBatch, SourceBatchItem
    from app.schemas import SourceCreate

    engine = create_engine(f'sqlite:///{tmp_path / "same-key.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    folder = tmp_path / 'docs'
    folder.mkdir()
    batch_id, item_id = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with sessions() as session:
        session.add(SourceBatch(id=batch_id, owner_user_id=1, fingerprint='f', request_snapshot='{"common_settings":{}}',
            location_type='local', created_at=now, updated_at=now,
            items=[SourceBatchItem(batch_id=batch_id, item_id=item_id, position=0, name='Docs', root_path=str(folder))]))
        session.commit()
    old_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(tmp_path)
    gate = Barrier(2)
    try:
        def call():
            with sessions() as session:
                source = _build_source(session, SourceCreate(id='batch-stable', name='Docs', root_path=str(folder)), 'batch-stable', str(folder))
                gate.wait()
                return _write_item(session, batch_id, item_id, 1, source, None, None)[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: call(), range(2)))
        assert [result['state'] for result in results] == ['created', 'created']
        assert results[0]['source_id'] == results[1]['source_id']
        with sessions() as session:
            assert session.query(Source).count() == 1
    finally:
        settings.allowed_source_paths = old_allowed
        engine.dispose()


def test_scheduler_error_reports_committed_source_with_warning(client, monkeypatch, temp_source_dir):
    from app.main import app
    payload = request_payload(temp_source_dir)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    def fail_schedule(source_id):
        raise RuntimeError('scheduler unavailable')
    monkeypatch.setattr(app.state.scheduler, 'update_source_schedule', fail_schedule)
    result = client.post(f"/api/sources/batches/{payload['id']}/items/{payload['items'][0]['id']}/create", json={})
    assert result.status_code == 200
    assert result.json()['state'] == 'created'
    assert 'schedule' in result.json()['warning']


def test_canonical_windows_identity_folds_drive_and_case():
    from app.api.source_batches import _identity
    assert _identity('agent', 'a', 'C:\\Shares\\Docs', True) == _identity('agent', 'a', 'c:\\shares\\docs', True)
    assert _identity('agent', 'a', '/srv/Docs', False) != _identity('agent', 'a', '/srv/docs', False)


def test_local_filesystem_checks_happen_before_write_lock(client, db_session, temp_source_dir, monkeypatch):
    import os

    from sqlalchemy import event

    from app.api import source_batches

    payload = request_payload(temp_source_dir)
    assert client.post('/api/sources/batches', json=payload).status_code == 201
    locked = False
    original_realpath = os.path.realpath

    def check_realpath(path, *args, **kwargs):
        if locked:
            from app.config import settings
            assert str(path) in settings.allowed_source_paths.split(','), 'unbounded path resolution held the writer lock'
        return original_realpath(path, *args, **kwargs)

    def before_execute(_conn, _cursor, statement, _params, _context, _many):
        nonlocal locked
        if statement == 'BEGIN IMMEDIATE':
            locked = True

    def after_transaction(_conn):
        nonlocal locked
        locked = False

    engine = db_session.get_bind()
    event.listen(engine, 'before_cursor_execute', before_execute)
    event.listen(engine, 'commit', after_transaction)
    event.listen(engine, 'rollback', after_transaction)
    monkeypatch.setattr(source_batches.os.path, 'realpath', check_realpath)
    try:
        response = client.post(f"/api/sources/batches/{payload['id']}/items/{payload['items'][0]['id']}/create", json={})
        assert response.status_code == 200, response.text
        assert response.json()['state'] == 'created'
    finally:
        event.remove(engine, 'before_cursor_execute', before_execute)
        event.remove(engine, 'commit', after_transaction)
        event.remove(engine, 'rollback', after_transaction)


def test_changed_allowed_root_symlink_fails_at_commit_boundary(client, db_session, tmp_path):
    from sqlalchemy import event

    from app.config import settings

    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    (first / 'folder').mkdir()
    link = tmp_path / 'allowed'
    link.symlink_to(first, target_is_directory=True)
    old_allowed = settings.allowed_source_paths
    settings.allowed_source_paths = str(link)
    engine = db_session.get_bind()
    changed = False

    def before_execute(_conn, _cursor, statement, _params, _context, _many):
        nonlocal changed
        if statement == 'BEGIN IMMEDIATE' and not changed:
            link.unlink()
            link.symlink_to(second, target_is_directory=True)
            changed = True

    event.listen(engine, 'before_cursor_execute', before_execute)
    try:
        payload = request_payload(str(link / 'folder'))
        assert client.post('/api/sources/batches', json=payload).status_code == 201
        result = client.post(f"/api/sources/batches/{payload['id']}/items/{payload['items'][0]['id']}/create", json={})
        assert result.status_code == 200, result.text
        assert result.json()['state'] == 'failed'
        assert db_session.query(Source).count() == 0
        assert changed
    finally:
        event.remove(engine, 'before_cursor_execute', before_execute)
        settings.allowed_source_paths = old_allowed
