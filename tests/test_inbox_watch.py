"""Inbox: mentions, watch levels, proposals, change notices and the baseline for the change screen."""
from conftest import login, register_user

from backend.services import project_history


def _project(c):
    register_user(c, 'alice')
    register_user(c, 'bob')
    register_user(c, 'carol')
    login(c, 'alice')
    did = c.post('/api/docs/create', json={'title': 'Doc', 'content': 'one\ntwo'}).json()['id']
    pid = c.get(f'/api/docs/{did}').json()['project_id']
    for name in ('bob', 'carol'):
        assert c.post(f'/api/projects/{pid}/members', json={'username': name, 'role': 'editor'}).status_code == 200
    return did, pid


def _inbox(c, user):
    login(c, user)
    return c.get('/api/notifications').json()


def test_mentions_reach_members_only_and_editing_notifies_new_names_once(c):
    did, pid = _project(c)
    cid = c.post(f'/api/docs/{did}/comments', json={'anchor': 1, 'text': 'hi @bob and @alice and @nobody'}).json()['id']
    inbox = _inbox(c, 'bob')
    assert inbox['unread'] == 1
    item = inbox['items'][0]
    assert (item['type'], item['actor'], item['project_id'], item['doc_id'], item['ref']) == ('mention', 'alice', pid, did, cid)
    assert _inbox(c, 'alice')['items'] == []  # not yourself
    login(c, 'alice')
    c.post(f'/api/docs/{did}/comments/{cid}/edit', json={'text': 'hi @bob and @carol'})
    assert _inbox(c, 'bob')['unread'] == 1  # bob was already mentioned
    assert _inbox(c, 'carol')['unread'] == 1


def test_inbox_read_one_and_all(c):
    did, _ = _project(c)
    c.post(f'/api/docs/{did}/comments', json={'anchor': 1, 'text': '@bob one'})
    c.post(f'/api/docs/{did}/comments', json={'anchor': 1, 'text': '@bob two'})
    login(c, 'bob')
    items = c.get('/api/notifications').json()['items']
    assert len(items) == 2
    assert c.post(f"/api/notifications/{items[0]['id']}/read").json() == {'ok': True}
    assert c.get('/api/notifications').json()['unread'] == 1
    assert c.post('/api/notifications/read-all').json() == {'marked': 1}
    assert c.get('/api/notifications').json()['unread'] == 0
    login(c, 'carol')
    assert c.post(f"/api/notifications/{items[1]['id']}/read").json() == {'ok': False}  # not carol's


def test_watch_level_default_set_and_validated(c):
    _, pid = _project(c)
    login(c, 'bob')
    assert c.get(f'/api/projects/{pid}/watch').json()['level'] == 'proposals'
    assert c.put(f'/api/projects/{pid}/watch', json={'level': 'everything'}).status_code == 400
    assert c.put(f'/api/projects/{pid}/watch', json={'level': 'all'}).json()['level'] == 'all'
    assert c.get(f'/api/projects/{pid}/watch').json()['level'] == 'all'


def test_proposals_follow_the_watch_level(c):
    did, pid = _project(c)
    login(c, 'carol')
    c.put(f'/api/projects/{pid}/watch', json={'level': 'mentions'})
    login(c, 'bob')
    file = {'kind': 'document', 'doc_id': did, 'path': 'main.typ', 'action': 'modify', 'base': 'one\ntwo',
            'content': 'one\nTWO', 'changes': [{'old_string': 'two', 'new_string': 'TWO'}]}
    r = c.post(f'/api/projects/{pid}/proposals', json={'title': 'Fix two', 'files': [file]})
    assert r.status_code == 200, r.text
    assert _inbox(c, 'bob')['items'] == []  # the author
    assert _inbox(c, 'carol')['items'] == []  # mentions only
    alice = _inbox(c, 'alice')['items']
    assert [(i['type'], i['text'], i['actor'], i['ref']) for i in alice] == [('proposal', 'Fix two', 'bob', r.json()['id'])]


def test_changes_notice_for_level_all_is_coalesced_and_seen_moves_the_baseline(c, monkeypatch):
    did, pid = _project(c)
    login(c, 'bob')
    c.put(f'/api/projects/{pid}/watch', json={'level': 'all'})
    login(c, 'carol')
    c.put(f'/api/projects/{pid}/watch', json={'level': 'proposals'})
    monkeypatch.setattr('backend.constants.SNAP_EVERY', -1)
    login(c, 'alice')
    project_history.auto(pid)
    project_history.auto(pid)
    bob = _inbox(c, 'bob')['items']
    assert [(i['type'], i['is_read']) for i in bob] == [('changes', False)]  # one item, refreshed
    assert _inbox(c, 'carol')['items'] == []
    login(c, 'bob')
    before = c.get(f'/api/projects/{pid}/watch').json()
    assert before['base']
    assert c.post(f'/api/projects/{pid}/watch/seen').status_code == 200
    after = c.get(f'/api/projects/{pid}/watch').json()
    assert after['seen_at'] > before['seen_at'] and after['base'] != before['base']  # baseline moved to the newest checkpoint
    assert c.get('/api/notifications').json()['unread'] == 0
