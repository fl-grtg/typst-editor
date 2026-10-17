"""The compact toolbar keeps insertion and staged uploads reachable."""
import re

import pytest
from playwright.sync_api import expect

from e2e.helpers import create_doc, register


@pytest.mark.parametrize('extension', ['csv', 'bib'])
@pytest.mark.parametrize('action', ['accept', 'discard'])
@pytest.mark.parametrize('change', ['replace', 'delete'])
def test_structured_proposal_actions_without_source_mode(page, extension, action, change):
    register(page, f'field_{extension}_{action[0]}_{change[0]}')
    create_doc(page, 'Structured review')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    document = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'Structured review')
    project = document['project_id']
    name = 'data.' + extension
    base = 'name,value\nalpha,Old title\n' if extension == 'csv' else '@book{key, title={Old title}, author={Jane}, year={2026}}\n'
    content = base.replace('Old title', 'New title')
    if extension == 'bib' and change == 'replace':
        content = content.replace('Jane', 'Joan')
    if change == 'delete':
        content = base.replace('Old title' if extension == 'csv' else 'title={Old title}, ', '')
    assert page.request.post(f'/api/projects/{project}/resources', data={'name': name, 'content': base}).ok
    response = page.request.post(f'/api/projects/{project}/proposals', data={'title': 'Field review', 'files': [{
        'kind': 'resource', 'path': name, 'action': 'modify', 'base': base, 'content': content,
        'changes': [{'old_string': base, 'new_string': content}],
    }]})
    assert response.ok, response.text()
    package = response.json()['id']
    page.reload()
    page.locator('#own .doc .t').filter(has_text='Structured review').click()
    expect(page.locator('#title')).to_have_text('Structured review')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    page.evaluate('entry => window.openTopPackage(entry)', {'project': project, 'id': package})
    page.wait_for_function('id => window.changeSession?.package?.id === id', arg=package)
    page.locator('#own .doc .t').filter(has_text=name).click()
    expect(page.locator('#title')).to_have_text(name)
    expect(page.locator('#cmWrap')).not_to_be_visible()
    if extension == 'csv':
        page.locator('.csv-proposed input').first.click()
    else:
        page.locator('.bib-proposed .proposalFieldAction').filter(has_text='Title').press('Enter')
    expect(page.locator('#pop')).to_be_visible()
    if extension == 'csv':
        row = page.locator('#pop .proposalCells tr').filter(has_text='B2')
        expect(row.locator('.qt')).to_have_text('Old title')
        if change == 'replace':
            expect(row.locator('.tx')).to_have_text('New title')
        else:
            expect(row.locator('.tx')).to_have_count(0)
    elif change == 'replace':
        expect(page.locator('#pop .proposalBibField').filter(has_text='Title').locator('.tx')).to_have_text('New title')
        expect(page.locator('#pop .proposalBibField').filter(has_text='Author(s)').locator('.tx')).to_have_text('Joan')
    else:
        expect(page.locator('#pop .tx')).to_have_count(0)
    expect(page.locator('#pop .qt').filter(has_text='Old')).to_contain_text('Old')
    page.locator('#pop .th .hd button').nth(0 if action == 'accept' else 1).click()
    expect(page.locator('#pop')).not_to_be_visible()
    if action == 'accept':
        page.wait_for_function('!window.changeSession')
    else:
        page.wait_for_function("[...window.changeSession.files.values()].every(f => f.content === f.base)")
    expect(page.locator('#cmWrap')).not_to_be_visible()
    resources = page.request.get(f'/api/projects/{project}/resources').json()['resources']
    assert next(r for r in resources if r['name'] == name)['content'] == (content if action == 'accept' else base)


def test_bib_draft_marks_and_opens_changed_input_immediately(page):
    register(page, 'bib_live_field')
    create_doc(page, 'Live Bib')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    document = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'Live Bib')
    project = document['project_id']
    base = '@book{key, title={Old title}, author={Jane}, year={2026}}\n'
    assert page.request.post(f'/api/projects/{project}/resources', data={'name': 'sources.bib', 'content': base}).ok
    page.reload()
    page.locator('#own .doc .t').filter(has_text='Live Bib').click()
    page.locator('#own .doc .t').filter(has_text='sources.bib').click()
    expect(page.locator('#wsTxt')).to_have_text('Live')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#suggestionToggle')).to_have_attribute('aria-pressed', 'true')
    title = page.locator('.bibField').filter(has=page.locator('span', has_text=re.compile('^Title$')))
    title.locator('textarea').fill('A longer new title')
    expect(title).to_have_class(re.compile('bib-proposed'))
    expect(title.locator('textarea')).to_be_focused()
    title.locator('textarea').click()
    expect(page.locator('#pop')).to_be_visible()
    assert page.locator('#pop').evaluate('pop => { const p = pop.getBoundingClientRect(), f = document.querySelector(".bib-proposed").getBoundingClientRect(); return p.bottom <= f.top || p.top >= f.bottom }')
    expect(page.locator('#pop .tx')).to_contain_text('longer new')
    expect(page.locator('#pop .bar b')).to_have_text('Title')
    page.locator('#pop .th .hd button').click()
    expect(title.locator('textarea')).to_have_value('Old title')
    expect(title).not_to_have_class(re.compile('bib-proposed'))
    resources = page.request.get(f'/api/projects/{project}/resources').json()['resources']
    assert next(r for r in resources if r['name'] == 'sources.bib')['content'] == base


def test_csv_review_accepts_and_discards_only_clicked_cell(page):
    register(page, 'csv_cell_review')
    create_doc(page, 'Cell review')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    document = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'Cell review')
    project = document['project_id']
    base = 'a,b,c,d\n1,2,,\n3,4,,\n'
    content = 'a,b,c,d\n1,2,first,\n3,4,,second\n'
    assert page.request.post(f'/api/projects/{project}/resources', data={'name': 'data.csv', 'content': base}).ok
    response = page.request.post(f'/api/projects/{project}/proposals', data={'title': 'Two cells', 'files': [{
        'kind': 'resource', 'path': 'data.csv', 'action': 'modify', 'base': base, 'content': content,
        'changes': [{'old_string': base, 'new_string': content}],
    }]})
    assert response.ok, response.text()
    package = response.json()['id']
    page.reload()
    page.locator('#own .doc .t').filter(has_text='Cell review').click()
    expect(page.locator('#title')).to_have_text('Cell review')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    page.evaluate('entry => window.openTopPackage(entry)', {'project': project, 'id': package})
    page.wait_for_function('id => window.changeSession?.package?.id === id', arg=package)
    page.locator('#own .doc .t').filter(has_text='data.csv').click()
    page.locator('.csvEditor input[aria-label="C2"]').click()
    expect(page.locator('#pop .proposalCells tr')).to_have_count(1)
    expect(page.locator('#pop .proposalCells th')).to_have_text('C2')
    expect(page.locator('#pop .tx')).to_have_text('first')
    expect(page.locator('#pop .qt')).to_have_count(0)
    expect(page.locator('#pop .bar b')).to_have_text('C2')
    page.locator('#pop .th .hd button').first.click()
    page.wait_for_function('window.changeSession?.package?.accepted === 1 && !window.changeSession.busy')
    resources = page.request.get(f'/api/projects/{project}/resources').json()['resources']
    expected = 'a,b,c,d\n1,2,first,\n3,4,,\n'
    assert next(r for r in resources if r['name'] == 'data.csv')['content'] == expected
    page.locator('.csvEditor input[aria-label="D3"]').click()
    expect(page.locator('#pop .proposalCells tr')).to_have_count(1)
    expect(page.locator('#pop .proposalCells th')).to_have_text('D3')
    expect(page.locator('#pop .tx')).to_have_text('second')
    page.locator('#pop .th .hd button').nth(1).click()
    page.wait_for_function("[...window.changeSession.files.values()].every(f => f.content === f.base)")
    expect(page.locator('.csv-proposed')).to_have_count(0)


def test_icon_toolbar_font_size_and_document_draft_label(page):
    register(page, 'icon_toolbar')
    create_doc(page, 'Bericht')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    assert page.locator('#insertMore').inner_text() == ''
    size = page.locator('#cmWrap').evaluate("node => parseInt(node.style.getPropertyValue('--ed'))")
    page.locator('#fPlus').click()
    assert page.locator('#cmWrap').evaluate("node => parseInt(node.style.getPropertyValue('--ed'))") == size + 1
    page.locator('#suggestionToggle').click()
    expect(page.locator('#cm .cm-content')).to_have_attribute('contenteditable', 'true')
    page.locator('#cm .cm-content').click()
    page.keyboard.press('ControlOrMeta+End')
    page.keyboard.insert_text('\nDraft addition')
    expect(page.locator('.package-modified .t').filter(has_text='Bericht')).to_be_visible()
    expect(page.locator('.package-file .t').filter(has_text='Bericht.typ')).to_have_count(0)
    for width in (1440, 1200, 900):
        page.set_viewport_size({'width': width, 'height': 900})
        assert page.locator('#docHead').evaluate("""head => {
          const bounds = head.getBoundingClientRect(), status = head.querySelector('.l2').getBoundingClientRect()
          return status.left >= bounds.left - 1 && status.right <= bounds.right + 1
        }""")


def test_insert_menu_opens_symbols_and_returns_focus(page):
    register(page, 'clean_insert')
    create_doc(page, 'Writing')
    page.locator('#insertMore').press('Enter')
    page.locator('#menu button').filter(has_text='Insert symbol').click()
    expect(page.locator('#symPop')).to_be_visible()
    expect(page.locator('#symPop input')).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.locator('#symPop')).not_to_be_visible()
    expect(page.locator('#insertMore')).to_be_focused()


def test_staged_delete_and_rename_can_be_discarded_per_file(page):
    register(page, 'undo_staged_file')
    create_doc(page, 'File undo')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    document = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'File undo')
    project = document['project_id']
    source = 'Original resource text'
    assert page.request.post(f'/api/projects/{project}/resources', data={'name': 'notes.typ', 'content': source}).ok
    page.reload()
    page.locator('#own .doc .t').filter(has_text='File undo').click()
    expect(page.locator('#title')).to_have_text('File undo')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    page.locator('#own .doc .t').filter(has_text='notes.typ').click()
    expect(page.locator('#title')).to_have_text('notes.typ')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#suggestionToggle')).to_have_attribute('aria-pressed', 'true')
    for action in ('Rename', 'Delete'):
        page.locator('#own .doc').filter(has_text='notes.typ').locator('button[title="Menu"]').click()
        page.locator('#modal button.pk').filter(has_text=action).click()
        if action == 'Rename':
            page.fill('#mInp', 'renamed.typ')
            page.click('#mYes')
        page.wait_for_function('action => [...window.changeSession.files.values()].some(f => f.action === action)', arg=action.lower())
        expect(page.locator('#cm .cm-content')).to_have_text(source)
        page.locator('.package-tools button[title="Menu"]').click()
        page.locator('#modal button.pk').filter(has_text='Discard file changes').click()
        page.wait_for_function("[...window.changeSession.files.values()].every(f => f.action === 'modify' && f.content === f.base)")
        expect(page.locator('#cm .cm-content')).to_have_attribute('contenteditable', 'true')
        expect(page.locator('#title')).to_have_text('notes.typ')
    resources = page.request.get(f'/api/projects/{project}/resources').json()['resources']
    assert next(r for r in resources if r['name'] == 'notes.typ')['content'] == source
    assert all(r['name'] != 'renamed.typ' for r in resources)


def test_starting_proposal_blocks_source_edits_until_ready(page):
    register(page, 'starting_proposal')
    create_doc(page, 'Slow proposal')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    document = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'Slow proposal')
    source = page.request.get(f'/api/docs/{document["id"]}').json()['content']
    pending = []
    pattern = '**/api/projects/*/proposals'
    page.route(pattern, lambda route: pending.append(route))
    with page.expect_request(re.compile(r'/api/projects/[^/]+/proposals$')):
        page.locator('#suggestionToggle').click()
    expect(page.locator('#cm .cm-content')).to_have_attribute('contenteditable', 'false')
    expect(page.locator('#suggestionToggle')).to_be_disabled()
    page.locator('#cm .cm-content').click()
    page.keyboard.insert_text('Must not enter the source')
    assert page.request.get(f'/api/docs/{document["id"]}').json()['content'] == source
    for route in pending:
        route.continue_()
    page.unroute(pattern)
    expect(page.locator('#suggestionToggle')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#cm .cm-content')).to_have_attribute('contenteditable', 'true')
    page.locator('#cm .cm-content').click()
    page.keyboard.insert_text('Draft only')
    expect(page.locator('.package-modified .t').filter(has_text='Slow proposal')).to_be_visible()
    assert page.request.get(f'/api/docs/{document["id"]}').json()['content'] == source


def test_review_across_empty_document_and_resource_toggle_preserve_view(page):
    errors = []
    page.on('pageerror', lambda error: errors.append(error.stack))
    register(page, 'review_transition')
    base = 'A source document with a forty-one offset.\n'
    document = page.request.post('/api/docs/create', data={'title': 'Report', 'content': base}).json()['id']
    project = page.request.get(f'/api/docs/{document}').json()['project_id']
    assert page.request.post(f'/api/projects/{project}/docs', data={'title': 'Empty', 'content': ''}).ok
    assert page.request.post(f'/api/projects/{project}/resources', data={'name': 'sources.bib', 'content': '@book{key, title={Writing}, year={2026}}\n'}).ok
    response = page.request.post(f'/api/projects/{project}/proposals', data={'title': 'Review offsets', 'files': [{
        'kind': 'document', 'doc_id': document, 'path': 'main.typ', 'action': 'modify',
        'base': base, 'content': base.replace('offset', 'position'),
        'changes': [{'old_string': base, 'new_string': base.replace('offset', 'position')}],
    }]})
    assert response.ok, response.text()
    package = response.json()['id']
    page.reload()
    page.locator('#own .doc .t').filter(has_text='Empty').click()
    expect(page.locator('#title')).to_have_text('Empty')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    page.evaluate('entry => window.openTopPackage(entry)', {'project': project, 'id': package})
    page.wait_for_function('id => window.changeSession?.package?.id === id', arg=package)
    page.locator(f'#tabs button[data-k="@doc/{document}"]').click()
    expect(page.locator('#title')).to_have_text('Report')
    expect(page.locator('#cm .cm-content')).to_contain_text('position')
    page.locator('.package-tools button[title="Back to editing"]').click()
    page.wait_for_function('!window.changeSession')
    page.locator('#own .doc .t').filter(has_text='sources.bib').click()
    expect(page.locator('#title')).to_have_text('sources.bib')
    expect(page.locator('#fMinus')).to_be_visible()
    expect(page.locator('#fPlus')).to_be_visible()
    page.locator('#suggestionToggle').click()
    page.wait_for_function('!!window.changeSession')
    expect(page.locator('body')).to_have_class(re.compile(r'\bfile-view\b'))
    expect(page.locator('#viewSeg')).not_to_be_visible()
    page.locator('#suggestionToggle').click()
    page.wait_for_function('!window.changeSession')
    expect(page.locator('#title')).to_have_text('sources.bib')
    expect(page.locator('#viewSeg')).not_to_be_visible()
    expect(page.locator('#cm .cm-content')).to_contain_text('@book{key')
    assert errors == []


def test_conflicting_source_keeps_draft_and_explains_problem(page):
    register(page, 'conflict_draft')
    response = page.request.post('/api/docs/create', data={'title': 'Conflict draft', 'content': 'alpha beta gamma\n'})
    document = response.json()['id']
    page.reload()
    page.locator('#own .doc .t').filter(has_text='Conflict draft').click()
    expect(page.locator('#wsTxt')).to_have_text('Live')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#cm .cm-content')).to_have_attribute('contenteditable', 'true')
    page.locator('#cm .cm-content').click()
    page.keyboard.press('ControlOrMeta+A')
    page.keyboard.insert_text('alpha BETA gamma\n')
    current = 'alpha replaced gamma\n'
    assert page.request.post(f'/api/docs/{document}/save', data={'content': current, 'force': True}).ok
    page.keyboard.press('ControlOrMeta+S')
    expect(page.locator('#modal')).to_be_visible()
    page.fill('#mInp', 'Conflicting proposal')
    page.click('#mYes')
    expect(page.locator('#toast')).to_contain_text('Your draft has been kept')
    page.wait_for_function('window.changeSession && !window.changeSession.busy')
    assert page.evaluate("[...window.changeSession.files.values()].find(f => f.kind === 'document').content") == 'alpha BETA gamma\n'
    assert page.request.get(f'/api/docs/{document}').json()['content'] == current


def test_own_repetitive_csv_proposal_can_be_viewed_and_withdrawn(page):
    register(page, 'repeat_csv')
    create_doc(page, 'CSV review')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    document = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'CSV review')
    project = document['project_id']
    base = 'a,b,c,d\n' + ',,,\n' * 7
    old = ',,,\n' * 5
    new = ',,,\n,,,\n,,changed,\n,,,\n,,,\n'
    content = base.replace(old, new, 1)
    assert page.request.post(f'/api/projects/{project}/resources', data={'name': 'data.csv', 'content': base}).ok
    response = page.request.post(f'/api/projects/{project}/proposals', data={'title': 'My CSV suggestion', 'files': [{
        'kind': 'resource', 'path': 'data.csv', 'action': 'modify', 'base': base, 'content': content,
        'changes': [{'old_string': old, 'new_string': new}],
    }]})
    assert response.ok, response.text()
    package = response.json()['id']
    page.reload()
    page.locator('#own .doc .t').filter(has_text='CSV review').click()
    expect(page.locator('#title')).to_have_text('CSV review')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    page.evaluate('entry => window.openTopPackage(entry)', {'project': project, 'id': package})
    page.wait_for_function('id => window.changeSession?.package?.id === id', arg=package)
    page.locator('#own .doc .t').filter(has_text='data.csv').click()
    expect(page.locator('#title')).to_have_text('data.csv')
    assert page.evaluate("[...window.changeSession.files.values()].find(f => f.path === 'data.csv').content") == content
    expect(page.locator('.package-modified .t').filter(has_text='data.csv')).to_be_visible()
    page.locator('.package-tools button[title="Menu"]').click()
    page.locator('#modal button.pk').filter(has_text='Delete package').click()
    page.click('#mYes')
    page.wait_for_function('!window.changeSession')
    assert page.request.get(f'/api/projects/{project}/proposals').json()['packages'] == []
    resources = page.request.get(f'/api/projects/{project}/resources').json()['resources']
    assert next(r for r in resources if r['name'] == 'data.csv')['content'] == base


def test_upload_in_proposal_is_submitted_without_writing_source(page):
    register(page, 'clean_proposal')
    create_doc(page, 'Proposal')
    expect(page.locator('#wsTxt')).to_have_text('Live')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#suggestionToggle')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.package-mode')).to_have_text('Unsent proposal')
    page.locator('#imgPick').set_input_files({'name': 'draft.csv', 'mimeType': 'text/csv', 'buffer': b'a,b\n1,2\n'})
    expect(page.locator('.package-file .t').filter(has_text='draft.csv')).to_be_visible()
    page.locator('.package-tools button[title="Back to editing"]').click()
    page.locator('#modal button.pk').first.click()
    page.fill('#mInp', 'Review upload')
    page.click('#mYes')
    expect(page.locator('#suggestionToggle')).to_have_attribute('aria-pressed', 'false')
    docs = page.request.get('/api/docs').json()['own']
    document = next(d for d in docs if d['title'] == 'Proposal')
    assert page.request.get(f'/api/docs/{document["id"]}/files/draft.csv').status == 404
    url = f'/api/projects/{document["project_id"]}/proposals'
    packages = page.request.get(url).json()['packages']
    assert len(packages) == 1
    proposal = page.request.get(url + '/' + packages[0]['id']).json()
    assert proposal['files'][0]['path'] == 'draft.csv'
    assert proposal['files'][0]['content'] == 'a,b\n1,2\n'


def test_document_only_guest_can_still_propose_text(page, browser, base_url):
    register(page, 'proposal_owner')
    response = page.request.post('/api/docs/create', data={'title': 'Shared proposal', 'content': 'Original shared'})
    document = response.json()['id']
    other = browser.new_context(base_url=base_url, locale='en-US')
    peer = other.new_page()
    try:
        register(peer, 'proposal_guest')
        assert page.request.post(f'/api/docs/{document}/share', data={'username': 'proposal_guest', 'role': 'reviewer'}).ok
        peer.reload()
        peer.locator('#shared .doc .t').filter(has_text='Shared proposal').click()
        expect(peer.locator('#cm .cm-content')).to_have_text('Original shared')
        expect(peer.locator('#wsTxt')).to_have_text('Live')
        peer.locator('#suggestionToggle').click()
        peer.wait_for_function('!!window.suggestionDraft')
        expect(peer.locator('.package-tools')).not_to_be_visible()
        peer.locator('#cm .cm-content').click()
        peer.keyboard.press('ControlOrMeta+A')
        peer.keyboard.insert_text('Suggested shared')
        peer.keyboard.press('ControlOrMeta+S')
        peer.wait_for_function('!window.suggestionDraft')
        assert page.request.get(f'/api/docs/{document}').json()['content'] == 'Original shared'
        comments = page.request.get(f'/api/docs/{document}/comments').json()['comments']
        assert comments[0]['suggestion_status'] == 'pending'
        assert comments[0]['replacement'] == 'Suggested shared'
    finally:
        other.close()


def test_large_binary_draft_survives_reload(page):
    register(page, 'large_proposal')
    create_doc(page, 'Large proposal')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#suggestionToggle')).to_have_attribute('aria-pressed', 'true')
    page.locator('#imgPick').set_input_files({'name': 'large.png', 'mimeType': 'image/png', 'buffer': b'\0' * (4 * 1024 * 1024)})
    expect(page.locator('.package-file .t').filter(has_text='large.png')).to_be_visible()
    page.wait_for_function('window.changeSession?.stashFailed === false')
    assert page.evaluate("""async () => {
      const s = window.changeSession
      const request = indexedDB.open('typst-proposal-drafts', 1)
      const db = await new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error) })
      const read = db.transaction('drafts').objectStore('drafts').get('typst-package-large_proposal-' + s.project)
      const saved = await new Promise(resolve => { read.onsuccess = () => resolve(read.result) })
      db.close()
      return window.changeSession === s && saved?.files.some(f => f.path === 'large.png' && f.content.length > 5 * 1024 * 1024)
    }""")
    page.once('dialog', lambda dialog: dialog.accept())
    page.reload()
    restored = page.evaluate("""async () => {
      const request = indexedDB.open('typst-proposal-drafts', 1)
      const db = await new Promise(resolve => { request.onsuccess = () => resolve(request.result) })
      const read = db.transaction('drafts').objectStore('drafts').getAll()
      const rows = await new Promise(resolve => { read.onsuccess = () => resolve(read.result) })
      db.close()
      return rows.map(row => ({ package: row.package, files: row.files.map(file => file.path) }))
    }""")
    assert any('large.png' in row['files'] for row in restored), restored
    page.locator('#own .doc .t').filter(has_text='Large proposal').click()
    expect(page.locator('#title')).to_have_text('Large proposal')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#modal')).to_be_visible()
    page.click('#mYes')
    expect(page.locator('.package-file .t').filter(has_text='large.png')).to_be_visible()
