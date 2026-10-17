from conftest import make_doc, register_user

from backend import sync


def test_batch_proposals_are_atomic_and_leave_source_unchanged(c):
    register_user(c, 'alice')
    did = make_doc(c, 'Batch', 'First passage\nSecond passage\n')
    response = c.post(f'/api/docs/{did}/suggestions/batch', json={'changes': [
        {'old_string': 'First passage', 'new_string': 'First improvement'},
        {'old_string': 'Second passage', 'new_string': 'Second improvement'},
    ]})
    assert response.status_code == 200, response.text
    assert len(response.json()['suggestions']) == 2
    assert sync.room_text(did) == 'First passage\nSecond passage\n'
    for proposal in response.json()['suggestions']:
        assert c.post(f'/api/docs/{did}/suggestions/{proposal["id"]}/accept').status_code == 200
    assert sync.room_text(did) == 'First improvement\nSecond improvement\n'


def test_batch_conflict_or_overlap_creates_no_partial_proposals(c):
    register_user(c, 'alice')
    did = make_doc(c, 'Atomic', 'Unique passage')
    url = f'/api/docs/{did}/suggestions/batch'
    assert c.post(url, json={'changes': [
        {'old_string': 'Unique', 'new_string': 'Better'},
        {'old_string': 'Gone', 'new_string': 'Missing'},
    ]}).status_code == 409
    assert c.get(f'/api/docs/{did}/comments').json()['comments'] == []
    assert c.post(url, json={'changes': [
        {'old_string': 'Unique passage', 'new_string': 'Better'},
        {'old_string': 'passage', 'new_string': 'Words'},
    ]}).status_code == 400
    assert c.get(f'/api/docs/{did}/comments').json()['comments'] == []


def test_first_text_can_be_proposed_for_an_empty_document(c):
    register_user(c, 'alice')
    did = make_doc(c, 'Empty proposal', '')
    result = c.post(f'/api/docs/{did}/suggestions/batch', json={'changes': [
        {'old_string': '', 'new_string': 'First text'},
    ]})
    assert result.status_code == 200, result.text
    assert sync.room_text(did) == ''
    cid = result.json()['suggestions'][0]['id']
    assert c.post(f'/api/docs/{did}/suggestions/{cid}/accept').status_code == 200
    assert sync.room_text(did) == 'First text'
