# web/ – frontend sources

`index.html` (repo root) is **generated** from the files in this directory. Edit the sources, then rebuild:

```bash
python web/build.py          # writes ../index.html
python web/build.py --check  # CI: fails if index.html is stale
```

The build is a plain concatenation (Python standard library only, no Node). Each line of the form
`@@include css/00-tokens.css@@` in `index.shell.html` is replaced verbatim by that file's content.
Output is byte-identical to a hand-written single file, so the served frontend is still one file.

## Layout

| Path | Content |
|---|---|
| `index.shell.html` | Head, markup (`<body>`), script tags and the include markers |
| `css/NN-*.css` | Stylesheet sections in cascade order (tokens, base, shell, editor, preview, menus, popovers, modal, responsive) |
| `js/00-imports.js` … `js/98-format-toolbar.js` | The main `<script type="module">`, split at its existing section boundaries; files are concatenated in filename order into **one module scope** |
| `js/ui-layer.js` | The second, classic `<script>` (menubar, export menu, rail) |

## Rules

- The `js/NN-*.js` files share one scope: they are *not* standalone modules. Order matters (filename prefix).
- Do not add banner comments that duplicate section names; keep the section comment at the top of each file.
- Next step (planned): turn these into real ES modules with explicit imports and a bundler. Until then, keep the
  byte-for-byte guarantee: `python web/build.py --check` must stay green.
