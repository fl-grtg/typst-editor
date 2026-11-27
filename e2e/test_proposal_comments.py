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
    expect(card.locator('.popStep')).to_have_text('3 / 3')
    expect(card).to_contain_text('Package note')
    expect(page.locator('#cm .cm-line')).to_have_count(2)
    assert [thread['text'] for thread in page.request.get(url).json()['comments'] if not thread['suggestion_status']] == ['Live note']
    page.keyboard.press('Escape')
    page.locator('[data-suggestion-id]').first.click()
    page.locator('#pop .sugAccept').click()
    _wait_for_content(page, did, 'one old text\nsecond row')
    expect(page.locator('#cm .cm-content')).to_contain_text('second row')
    page.wait_for_function("[...window.changeSession.files.values()].some(f => f.kind === 'document' && f.content.startsWith('one new text') && f.content.endsWith('second row'))")
