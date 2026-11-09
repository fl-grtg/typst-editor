"""Word count status follows document and file tab switches.

The topbar status must not keep the previous buffer's count when another
text attachment (.bib, .typ, .csv, .json, ...), a template or a binary
attachment opens, when an empty document is opened, or when the last
document is closed.
"""
import re

from helpers import create_doc, open_private_copy, register, type_source
from playwright.sync_api import expect


def _doc_id(page, title):
    return next(d['id'] for d in page.request.get('/api/docs').json()['own'] if d['title'] == title)


def test_word_count_follows_tab_and_document_switches(page):
    register(page, 'e2e_word_count')
    create_doc(page, 'Word count doc')
    doc_id = _doc_id(page, 'Word count doc')
    type_source(page, 'one two three four five')
    expect(page.locator('#pos')).to_contain_text('5 words')

    response = page.request.post(
        f'/api/docs/{doc_id}/files/sources.bib/text',
        data={'content': '@book{key, title={Some bibliography words here}, year={2026}}'},
    )
    assert response.ok, response.text()
    bib = page.locator('#tabs button.tab').filter(has_text='sources.bib')
    expect(bib).to_be_visible()
    bib.click()
    expect(page.locator('#pos')).to_contain_text('6 words')  # active .bib text, not main.typ
    expect(page.locator('#save')).not_to_contain_text('words')  # save state stays clean

    response = page.request.post(f'/api/docs/{doc_id}/files/chapter.typ/text', data={'content': 'alpha beta gamma'})
    assert response.ok, response.text()
    chapter = page.locator('#tabs button.tab').filter(has_text='chapter.typ')
    expect(chapter).to_be_visible()
    chapter.click()
    expect(page.locator('#pos')).to_contain_text('3 words')

    response = page.request.post(
        f'/api/docs/{doc_id}/files/data.csv/text',
        data={'content': 'alpha,beta,gamma\none,two,three\n'},
    )
    assert response.ok, response.text()
    sheet = page.locator('#tabs button.tab').filter(has_text='data.csv')
    expect(sheet).to_be_visible()
    sheet.click()
    expect(page.locator('#pos')).to_contain_text('2 words')  # table editor counts its source text

    response = page.request.post(
        f'/api/docs/{doc_id}/files/config.json/text',
        data={'content': '{"words": "one two three"}'},
    )
    assert response.ok, response.text()
    config = page.locator('#tabs button.tab').filter(has_text='config.json')
    expect(config).to_be_visible()
    config.click()
    expect(page.locator('#pos')).to_contain_text('4 words')

    response = page.request.post(
        f'/api/docs/{doc_id}/files',
        multipart={'f': {'name': 'pixel.png', 'mimeType': 'image/png', 'buffer': b'\x89PNG\r\n\x1a\n'}},
    )
    assert response.ok, response.text()
    picture = page.locator('#tabs button.tab').filter(has_text='pixel.png')
    expect(picture).to_be_visible()
    picture.click()
    expect(page.locator('#pos')).not_to_contain_text('words')  # binary placeholder has no word count

    page.locator('#tabs button.tab').first.click()
    expect(page.locator('#pos')).to_contain_text('5 words')

    open_private_copy(page, 'Word count template.typ')
    expect(page.locator('#pos')).to_contain_text('5 words')  # template text is a normal buffer too
    page.locator('#own .doc .t').filter(has_text=re.compile(r'^Word count doc$')).click()
    expect(page.locator('#title')).to_have_text('Word count doc')
    expect(page.locator('#pos')).to_contain_text('5 words')

    create_doc(page, 'Empty word count doc')
    expect(page.locator('#pos')).not_to_contain_text('words')  # empty document: no stale count
    type_source(page, 'alpha beta gamma delta')
    expect(page.locator('#pos')).to_contain_text('4 words')

    page.locator('#own .doc .t').filter(has_text=re.compile(r'^Word count doc$')).click()
    expect(page.locator('#title')).to_have_text('Word count doc')
    expect(page.locator('#pos')).to_contain_text('5 words')

    row = page.locator('#own .doc').filter(has_text=re.compile(r'^Word count doc$'))  # no doc open: welcome must drop the last count
    row.hover()
    row.locator('button.mini[data-side-menu]').click()
    page.get_by_role('menuitem', name='Move to trash').click()
    page.click('#mYes')
    expect(page.locator('#title')).to_have_text('Welcome')
    expect(page.locator('#pos')).not_to_contain_text('words')
