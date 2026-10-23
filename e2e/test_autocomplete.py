"""Completion lists must follow edits while the popup stays open."""
import re

import pytest
from helpers import create_doc, register, type_source
from playwright.sync_api import expect


@pytest.mark.parametrize(("initial", "suffix", "wanted", "stale"), [
    ("#", "sho", "#show", "#set"),
    ("#set pad(", "x", "x", "y"),
    ('#set page(paper: "', "a4", '"a4"', '"a3"'),
    ('#include "', "plot", "plot.typ", "photo.typ"),
])
def test_completion_list_updates_while_typing(page, initial, suffix, wanted, stale):
    register(page, f"autocomplete_{suffix}")
    create_doc(page, "Completions")
    if initial.startswith('#include'):
        doc_id = page.locator('.doc.cur').get_attribute('data-package-key').split(':')[1]
        for name in ('plot.typ', 'photo.typ'):
            response = page.request.post(f'/api/docs/{doc_id}/files', multipart={
                'f': {'name': name, 'mimeType': 'text/plain', 'buffer': b'Included text'},
            })
            assert response.ok, response.text()
        # Reopen to load the uploaded names through the normal document flow.
        page.locator('.doc.cur').click()
        type_source(page, '= Files ready')
        expect(page.locator('#preview .pvPage[data-done]').first).to_be_visible(timeout=60_000)
    type_source(page, initial)
    page.keyboard.press('Control+Space')
    labels = page.locator('.cm-tooltip-autocomplete .cm-completionLabel')
    old = labels.filter(has_text=re.compile(r'^' + re.escape(stale) + r'$'))
    target = labels.filter(has_text=re.compile(r'^' + re.escape(wanted) + r'$'))
    expect(old).to_be_visible()
    page.keyboard.type(suffix)
    expect(target).to_be_visible()
    expect(old).to_have_count(0)
    for _ in suffix:
        page.keyboard.press('Backspace')
    expect(old).to_be_visible()
