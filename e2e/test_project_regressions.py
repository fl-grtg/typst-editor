"""Project file create/rename flows use server names and list the references that follow."""
from helpers import create_doc, register
from playwright.sync_api import expect


def test_file_server_name_and_rename_preview(page):
    register(page, 'project_module_ui')
    create_doc(page, 'Workspace')
    head = page.locator('aside .project-group').filter(has_text='Workspace').locator('.fhd.project')
    head.hover()
    head.locator('button.mini').first.click()
    page.locator('#menu button').filter(has_text='New module').click()
    page.locator('#submenu button').filter(has_text='.typ').first.click()
    inp = page.locator('aside input.renameInput')
    expect(inp).to_be_visible()
    inp.fill('Änderungen')
    inp.press('Enter')
    # The UI opens the name the server returns (NFC-normalized, umlauts kept).
    tab = page.locator('#tabs button.tab').filter(has_text='Änderungen.typ')
    expect(tab).to_have_attribute('aria-selected', 'true')
    tab.dblclick()
    page.fill('#mInp', 'renamed.typ')
    page.click('#mYes')  # nothing quotes the file: renamed at once, no confirmation dialog
    expect(page.locator('#modal')).to_be_hidden()
    expect(page.locator('#tabs button.tab').filter(has_text='renamed.typ')).to_be_visible()
    expect(page.locator('#tabs button.tab').filter(has_text='Änderungen.typ')).to_have_count(0)
