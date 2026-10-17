from conftest import login, register_user


def test_spelling_is_saved_per_account(c):
    register_user(c, 'alice')
    assert c.get('/api/me').json()['spell_language'] == 'auto'
    assert c.post('/api/me/preferences', json={'spell_language': 'de'}).status_code == 200
    register_user(c, 'bob')
    assert c.get('/api/me').json()['spell_language'] == 'auto'
    c.post('/api/me/preferences', json={'spell_language': 'off'})
    login(c, 'alice')
    assert c.get('/api/me').json()['spell_language'] == 'de'
    login(c, 'bob')
    assert c.get('/api/me').json()['spell_language'] == 'off'


def test_spelling_preferences_require_login_and_valid_language(c):
    assert c.post('/api/me/preferences', json={'spell_language': 'de'}).status_code == 401
    register_user(c, 'alice')
    assert c.post('/api/me/preferences', json={'spell_language': 'garbage'}).status_code == 400
    assert c.get('/api/me').json()['spell_language'] == 'auto'


def test_spelling_survives_account_rename(c):
    register_user(c, 'alice')
    c.post('/api/me/preferences', json={'spell_language': 'de'})
    response = c.post('/api/me/name', json={'name': 'renamed', 'password': 'pass1234'})
    assert response.status_code == 200, response.text
    assert c.get('/api/me').json()['spell_language'] == 'de'
