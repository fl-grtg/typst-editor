"""Proposal mode keeps discussions at changes and can decide live suggestions."""
from playwright.sync_api import expect

from e2e.helpers import create_doc, put_source, register


def _wait_for_content(page, did, content):
    for _ in range(50):
        if page.request.get(f'/api/docs/{did}').json()['content'] == content:
            return
        page.wait_for_timeout(200)
    assert page.request.get(f'/api/docs/{did}').json()['content'] == content


def test_proposal_comments_stay_at_changes_and_live_suggestions_can_be_decided(page):
    register(page, 'proposal_comments')
    create_doc(page, 'Proposal comments')
    put_source(page, 'one old text\nsecond line')
    document = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'Proposal comments')
    did = document['id']
    _wait_for_content(page, did, 'one old text\nsecond line')
    url = f'/api/docs/{did}/comments'
    assert page.request.post(url, data={'anchor': 1, 'quote': 'old', 'anchor_quote': 'old', 'text': 'Live note'}).ok
    assert page.request.post(f'/api/docs/{did}/suggestions/batch', data={'changes': [{'old_string': 'second line', 'new_string': 'second row'}]}).ok
    page.reload()
    page.locator('#own .doc .t').filter(has_text='Proposal comments').click()
    expect(page.locator('#wsTxt')).to_have_text('Live')
    expect(page.locator('[data-comment-id]')).to_have_text('old')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#suggestionToggle')).to_have_attribute('aria-pressed', 'true')
    page.locator('[data-comment-id]').dblclick()
    page.keyboard.type('new')
    expect(page.locator('#sugBar')).to_contain_text('1')
    page.locator('[data-package-change]').first.click()
    card = page.locator('#pop')
    expect(card.locator('.sugAdd')).to_have_text('new')
    expect(card.locator('.popStep')).to_have_text('1 / 2')
    expect(card).not_to_contain_text('Live note')
    card.locator('input[id^="popPackageComment"]').fill('Package note')
    card.locator('input[id^="popPackageComment"]').press('Enter')
    expect(card.locator('.popStep')).to_have_text('1 / 2')  # the note belongs to the change card, not a page of its own
    expect(card.locator('.changeTalk')).to_contain_text('Package note')
    card.locator('.changeTalk input[id^="r_"]').fill('Second thought')
    card.locator('.changeTalk input[id^="r_"]').press('Enter')
    expect(card.locator('.changeTalk')).to_contain_text('Second thought')
    expect(card.locator('.changeTalk')).to_have_count(1)
    card.locator('.changeTalk .hd .acts button.danger').first.click()
    expect(card.locator('.changeTalk')).to_have_count(0)
    expect(card.locator('.sugAdd')).to_have_text('new')  # the change card stays open without its discussion
    expect(page.locator('#cm .cm-line')).to_have_count(2)
    assert [thread['text'] for thread in page.request.get(url).json()['comments'] if not thread['suggestion_status']] == ['Live note']
    page.keyboard.press('Escape')
    page.locator('[data-suggestion-id]').first.click()
    page.locator('#pop .sugAccept').click()
    _wait_for_content(page, did, 'one old text\nsecond row')
    expect(page.locator('#cm .cm-content')).to_contain_text('second row')
    page.wait_for_function("[...window.changeSession.files.values()].some(f => f.kind === 'document' && f.content.startsWith('one new text') && f.content.endsWith('second row'))")


def test_a_proposal_can_only_resolve_a_comment(page):
    register(page, 'proposal_resolve')
    create_doc(page, 'Proposal resolve')
    put_source(page, 'one old text')
    did = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'Proposal resolve')['id']
    _wait_for_content(page, did, 'one old text')
    assert page.request.post(f'/api/docs/{did}/comments', data={'anchor': 1, 'quote': 'old', 'anchor_quote': 'old', 'text': 'Live note'}).ok
    page.reload()
    page.locator('#own .doc .t').filter(has_text='Proposal resolve').click()
    expect(page.locator('[data-comment-id]')).to_have_text('old')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#sugSend')).to_be_hidden()
    page.locator('[data-comment-id]').click()
    page.locator('#pop button[title="Done"]').click()
    expect(page.locator('#sugBar')).to_contain_text('1')
    page.locator('#sugSend').click()
    page.locator('#mYes').click()
    expect(page.locator('#sugBar')).to_be_hidden()
    project = page.request.get(f'/api/docs/{did}').json()['project_id']
    package, = page.request.get(f'/api/projects/{project}/proposals').json()['packages']
    assert (package['file_count'], package['comment_changes']) == (0, 1)
    assert page.request.get(f'/api/docs/{did}/comments').json()['comments'][0]['resolved'] == 0


def test_a_reply_alone_is_sent_as_a_discussion_and_closed_as_done(page):
    register(page, 'proposal_talk')
    create_doc(page, 'Proposal talk')
    put_source(page, 'one old text')
    did = next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == 'Proposal talk')['id']
    _wait_for_content(page, did, 'one old text')
    assert page.request.post(f'/api/docs/{did}/comments', data={'anchor': 1, 'quote': 'old', 'anchor_quote': 'old', 'text': 'Live note'}).ok
    page.reload()
    page.locator('#own .doc .t').filter(has_text='Proposal talk').click()
    expect(page.locator('[data-comment-id]')).to_have_text('old')
    page.locator('#suggestionToggle').click()
    expect(page.locator('#sugSend')).to_be_hidden()
    page.locator('[data-comment-id]').click()
    page.locator('#pop input[id^="r_"]').fill('Why?')
    page.locator('#pop input[id^="r_"]').press('Enter')
    expect(page.locator('#sugSend')).to_be_visible()
    page.keyboard.press('Escape')
    page.locator('#sugSend').click()
    page.locator('#mYes').click()
    expect(page.locator('#sugBar')).to_be_hidden()
    project = page.request.get(f'/api/docs/{did}').json()['project_id']
    package, = page.request.get(f'/api/projects/{project}/proposals').json()['packages']
    assert (package['file_count'], package['comment_changes'], package['open']) == (0, 0, True)
    page.evaluate('a => window.openTopPackage({ project: a[0], id: a[1] })', [project, package['id']])
    expect(page.locator('#sugSend')).to_have_text('Done')
    page.locator('#sugSend').click()
    expect(page.locator('#sugBar')).to_be_hidden()
    assert page.request.get(f'/api/projects/{project}/proposals').json()['packages'] == []
