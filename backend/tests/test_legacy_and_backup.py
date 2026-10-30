"""MU-9 at read time (legacy statement-v1 VERIFIED results are never presented as current VERIFIED) and the backup
tool's fidelity (field order, compound index order, order-independent digest)."""

from tests.permit_fakes import ScriptedModel, make_client
from tests.test_permit_official_sources import auth, ingest_regulamento, run_matter


def _verified_matter():
    client = make_client(ScriptedModel())
    client.__enter__()
    ingest_regulamento(client)
    mid, token = run_matter(client)
    return client, mid, token


def test_a_verified_matter_under_a_protocol_the_floor_no_longer_admits_reads_as_legacy():
    client, mid, token = _verified_matter()
    try:
        repo = client.app.state.permit_workflow._repo
        assert client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()["assessment_status"] == "verified_assessment"
        latest = repo.verifications[mid][-1]
        repo.verifications[mid][-1] = latest.model_copy(update={"protocol": "statement-v1"})  # a legacy record
        matter = client.get(f"/api/permit/matters/{mid}", headers=auth(token)).json()
        assert matter["assessment_status"] == "superseded_assessment" and matter["superseded_protocol"] == "statement-v1"
        assert "Superseded assessment" in matter["outcome_note"]
        report = client.get(f"/api/permit/matters/{mid}/report", headers=auth(token)).json()["assessment"]
        assert report["status"] == "PENDING_CONFIRMATION" and report["verification"]["current"] is False
        assert report["verification"]["protocol"] == "statement-v1"  # provenance kept, shown as history
        assert repo.matters[mid].superseded_protocol is None  # read-time only: the stored matter is untouched
    finally:
        client.__exit__(None, None, None)


def test_a_current_protocol_stays_verified():
    client, mid, token = _verified_matter()
    try:
        report = client.get(f"/api/permit/matters/{mid}/report", headers=auth(token)).json()["assessment"]
        assert report["status"] == "VERIFIED" and report["verification"]["current"] is True
    finally:
        client.__exit__(None, None, None)


def _backup_module():
    from app.db import backup
    return backup


def test_backup_digest_ignores_field_order_but_files_keep_it():
    b = _backup_module()
    a, z = '{"_id": "1", "b": 2, "a": 1}', '{"_id": "1", "a": 1, "b": 2}'
    assert b._digest([a]) == b._digest([z]) and b._digest([a]) != b._digest(['{"_id": "1", "a": 1, "b": 3}'])


def test_backup_keeps_compound_index_key_order():
    b = _backup_module()
    spec = b._index_spec({"v": 2, "key": {"property_id": 1, "created_at": -1}, "name": "property_id_1_created_at_-1"})
    assert spec["key"] == [["property_id", 1], ["created_at", -1]]
