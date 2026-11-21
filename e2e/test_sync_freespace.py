"""Click-Sync in freier Fläche und über Links: jede Stelle der Seite gehört zur nächsten Zeile, Links folgen ihrem Ziel.

Die Brüche sind gegen das Typst-0.15.1-Layout vermessen; ein Toolchain-Wechsel soll hier laut scheitern.
"""
import re

from playwright.sync_api import expect
from test_sync_fallbacks import _click, _pos, _setup

SRC = """#set heading(numbering: "1.")
#set math.equation(numbering: "(1)")
= Alpha
A long first paragraph line that clearly fills the whole width of the text block and wraps onto a second line here.

Short line.

- First item
- Second item

$ a + b = c $ <eq>

See @eq and @knuth for details.

#columns(2)[#lorem(60)]

#bibliography("refs.bib")
"""
LINES = SRC.split("\n")
BIB = b"""@book{knuth,
  title={The TeXbook},
  author={Knuth, Donald},
  year={1984},
  publisher={Addison-Wesley}
}
"""


def _fixture(page, slug):
    _setup(page, slug, 'Free space doc', SRC, files=(('refs.bib', 'text/plain', BIB),))


def _main(page):
    tab = page.locator('#tabs button.tab').first
    if tab.get_attribute('aria-selected') != 'true':
        tab.click()
        page.wait_for_timeout(800)


def test_free_space_belongs_to_the_nearest_line(page):
    _fixture(page, 'e2e_sync_free')
    for fx, fy, want, what in [
        (0.80, 0.1492, 6, 'right of a short line'),
        (0.75, 0.1735, 8, 'right of a list item'),
        (0.05, 0.1906, 9, 'left margin beside a list item'),
        (0.70, 0.2153, 11, 'between a formula and its number'),
        (0.869, 0.2153, 11, 'the equation number'),
        (0.80, 0.2407, 13, 'right of a sentence end'),
        (0.128, 0.0868, 3, 'the heading number'),
    ]:
        _click(page, 1, fx, fy)
        line, col = _pos(page)
        assert line == want, f"{what}: Ln {line}:{col}, want {want}"
    _click(page, 1, 0.80, 0.2407)
    assert _pos(page)[1] >= LINES[12].index('details'), 'right of the line: the caret goes to its end'


def test_generated_text_in_columns_lands_on_its_call(page):
    _fixture(page, 'e2e_sync_free_cols')
    _click(page, 1, 0.30, 0.3333)  # lorem inside #columns
    line, col = _pos(page)
    assert line == 15 and col >= LINES[14].index('#lorem'), f"lorem in columns: Ln {line}:{col}"
    _click(page, 1, 0.80, 0.3333)  # empty right column beside it
    line, col = _pos(page)
    assert line == 15, f"blank column: Ln {line}:{col}"


def test_bibliography_and_reference_links(page):
    _fixture(page, 'e2e_sync_free_bib')
    _click(page, 1, 0.27, 0.4725)  # "The TeXbook" in the list: its title field
    expect(page.locator('#tabs button.tab[aria-selected="true"]')).to_have_text(re.compile(r'refs\.bib'))
    assert _pos(page)[0] == 2, f"title field: Ln {_pos(page)}"
    _main(page)
    _click(page, 1, 0.20, 0.4515)  # the generated "Bibliography" title
    assert _pos(page)[0] == 17, f"bibliography title: Ln {_pos(page)}"
    _click(page, 1, 0.278, 0.2407)  # "[1]" citation link: the entry, from its key line
    expect(page.locator('#tabs button.tab[aria-selected="true"]')).to_have_text(re.compile(r'refs\.bib'))
    assert _pos(page)[0] == 1, f"citation link: Ln {_pos(page)}"
    _main(page)
    _click(page, 1, 0.19, 0.2407)  # "Equation 1" reference link: the formula
    assert _pos(page)[0] == 11, f"equation link: Ln {_pos(page)}"


LONG = "".join(f"= Part {i}\n" + "Body sentence number {i} for the long document. " * 12 + "\n\n" for i in range(30))

EDGE = """(el) => el.scrollTop <= 2 ? 'top' : el.scrollTop + el.clientHeight >= el.scrollHeight - 2 ? 'bottom' : 'middle'"""


def test_editor_ends_reach_the_preview_ends(page):
    _setup(page, 'e2e_sync_edges', 'Edge doc', LONG)
    pv, ed = page.locator('#preview'), page.locator('#cm .cm-scroller')
    box = ed.bounding_box()
    assert box
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    for _ in range(3):  # the reader wheels the editor to its very end
        page.mouse.wheel(0, 40000)
        page.wait_for_timeout(500)
    assert ed.evaluate(EDGE) == 'bottom'
    page.wait_for_timeout(1500)
    assert pv.evaluate(EDGE) == 'bottom', 'editor at its end: the preview shows the last page end'
    for _ in range(3):
        page.mouse.wheel(0, -40000)
        page.wait_for_timeout(500)
    assert ed.evaluate(EDGE) == 'top'
    page.wait_for_timeout(1500)
    assert pv.evaluate(EDGE) == 'top', 'editor at its top: the preview shows the first page top'
    pbox = pv.bounding_box()
    assert pbox
    page.mouse.move(pbox['x'] + pbox['width'] / 2, pbox['y'] + pbox['height'] / 2)
    for _ in range(3):  # and the other way round
        page.mouse.wheel(0, 40000)
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500)
    assert pv.evaluate(EDGE) == 'bottom'
    assert ed.evaluate(EDGE) == 'bottom', 'preview at its end: the editor shows the last line'
