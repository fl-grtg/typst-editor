"""Project module create/rename flows use server names and explicit references."""
from helpers import create_doc, register
from playwright.sync_api import expect


def test_module_server_name_and_rename_preview(page):
    register(page, 'project_module_ui')
    create_doc(page, 'Workspace')
    page.click('#tabs button.tadd')
    page.locator('#modal button.pk').nth(1).click()
    page.locator('#modal button.pk').filter(has_text='.typ').first.click()
    page.fill('#mInp', 'Änderungen')
    page.click('#mYes')
    tab = page.locator('#tabs button.tab').filter(has_text='_nderungen.typ')
    expect(tab).to_have_attribute('aria-selected', 'true')
    tab.dblclick()
    page.fill('#mInp', 'renamed.typ')
    page.click('#mYes')
    expect(page.locator('#modal')).to_contain_text('No static references found')
    expect(page.locator('#modal')).to_contain_text('not changed automatically')
    page.click('#mYes')
    expect(page.locator('#tabs button.tab').filter(has_text='renamed.typ')).to_be_visible()
    expect(page.locator('#tabs button.tab').filter(has_text='_nderungen.typ')).to_have_count(0)
