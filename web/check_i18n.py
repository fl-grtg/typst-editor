#!/usr/bin/env python3
"""i18n consistency check (Wave 1B).

Fails when:
  * a t('area.key') / data-i18n*="area.key" key has no entry in
    web/i18n/en/<area>.json or web/i18n/de/<area>.json;
  * a user-visible string literal in web/js/**/*.js is hardcoded instead of
    going through t() (outside the explicit allowlist below);
  * visible text / placeholder / title / aria-label / alt in
    web/index.shell.html lacks a data-i18n* twin (outside the allowlist).

Run:  python web/check_i18n.py   (also wired into `make check` + CI lint)

Known limitations (documented, accepted): single-word literals are only
flagged when they match FORBIDDEN_SINGLE (a novel one-word label slips
through — keep the list in sync when adding UI words); backtick literals
with ${} and whole URL lines are skipped; multiline t('…') calls are not
seen (none exist — keep keys on one line).
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parent
SHELL = WEB / "index.shell.html"
JS_FILES = sorted(WEB.glob("js/**/*.js"))
I18N = WEB / "i18n"
LANGS = ("en", "de")

T_CALL = re.compile(r"""\bt\s*\(\s*(['"])((?:\\\1|(?!\1)[^\\])*?)\1""")
T_FIRSTARG = re.compile(r"""\bt\s*\(\s*$""")
I18N_ATTR = re.compile(r"""data-i18n(?:-html|-ph|-title|-aria)?\s*=\s*(['"])(.*?)\1""")
LIT = re.compile(r"""('(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`)""")
LETTER = re.compile(r"[A-Za-zäöüÄÖÜß]")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}

# Lines 1E rewrote (vendor URLs, WASM): never touch, never flag.
URL_LINE = re.compile(r"vendor/|https?://|\.wasm|workerSrc")
# Whole-line technical skips (locale-independent code/data, not UI prose).
SKIP_LINE_RES = [
    re.compile(r"T_BLOCKED"),  # CodeMirror node names incl. 'Error'
    re.compile(r"^\s*const (SYMS|SYN|T_KW|T_SNIP|STARTERS)\b"),  # symbol tables, snippets, template content
    re.compile(r"\.style\."),  # CSS values ('1px solid var(--line)', ...)
    re.compile(r"className|classList\."),  # CSS classes ('typ-hover full', 'save primary', ...)
]
EL_CLASS = re.compile(r"""\bel\(\s*(['"])[^'"]*\1\s*,\s*$""")  # literal is el()'s class arg
CALL_ARG = re.compile(
    r"""(getElementById|querySelector(All)?|closest|matches|getAttribute|"""
    r"""hasAttribute|removeAttribute|setAttribute|createElement|"""
    r"""addEventListener|removeEventListener|appendChild|insertBefore|"""
    r"""matchMedia|getPropertyValue)\s*\(\s*$"""
)
# web/js/10-cm-setup.js is a Typst syntax reference (hover docs), not UI
# prose: locale-independent by design, translating it would confuse.
SKIP_FILES = {"10-cm-setup.js"}

# Exact hardcoded strings that are NOT user-visible UI (console-only,
# protocol, keys, selectors, file names, inserted document defaults ...).
ALLOW_EXACT = {
    # console-only (never rendered)
    "anchor save failed", "file list stale, using cache", "shares failed",
    "invites failed", "comments failed", "comments poll failed",
    "session restore failed", "watchSidebar",
    "Compiler still loading - network/adblock issue.",
    # protocol / technical
    "HTTP ", "Content-Type", "application/json", "text/plain;charset=utf-8",
    "image/svg+xml", "application/pdf", "text/plain", "use strict",
    # boot fallback in index.shell.html: module (incl. t()) may be dead there
    "Something went wrong – ", "Reload",
    "App still loading – wait or reload",
    "App still loading – check network/adblock, then ",
    # template content / Typst code (locale-independent document defaults)
    "Text", "link", "Tutorial", "DELETE",
    # brand
    "Typst Editor",
}
# Starter templates (inserted document content, not UI chrome).
ALLOW_EXACT |= {
    '#set page(paper: "a4", margin: 2cm)\n#set text(size: 11pt)\n#set heading(numbering: "1.")\n\n= Introduction\n\nText here …\n',
    '#set page(paper: "presentation-16-9", margin: 1.5cm)\n#set text(size: 20pt)\n\n= Slide 1\n\n- First point\n- Second point\n\n= Slide 2\n\nText here …\n',
}
# Agent prompt: English instructions + URL for an AI agent, must stay English.
ALLOW_EXACT |= {
    "Install the Typst Editor skill from https://raw.githubusercontent.com/fl-grtg/typst-editor/main/skills/typst-editor/SKILL.md and follow its section 0 to connect to my Typst server. Ask me for server URL and API key if missing.",
}
ALLOW_RES = [
    re.compile(r"^[#=$/`+<@]"),  # Typst/HTML/code inserts ('#fig', '= x', '<p ..>', ...)
    re.compile(r"^\s+[a-z][\w-]*\s*$"),  # CSS class fragments (' on', ' cur')
    re.compile(r"^[\d\s.pxem%()/-]+$"),  # CSS dimensions ('12px 0', '4px 9px')
]
# Comparison values are never displayed (=== 'Error' is a node name, ...).
CMP_PREFIX = re.compile(r"(===|!==|==|!=)\s*$")
# Single words (no space) that are UI chrome and must go through t().
FORBIDDEN_SINGLE = {
    "OK", "Add", "New", "Blank", "Report", "Slides", "Document", "Template",
    "Folder", "Password", "Username", "Reader", "Owner", "Trash", "Share",
    "Settings", "Close", "Cancel", "Create", "Delete", "Remove", "Upload",
    "Download", "Retry", "Send", "Copy", "Copied", "Restore", "Duplicate",
    "Rename", "Replace", "Comment", "Reply", "Done", "Edit", "Empty", "Live",
    "Offline", "Never", "File", "View", "Help", "Insert", "Media", "History",
    "Symbols", "Zoom", "Font", "Tabs", "Avatar", "Name", "Account", "Backup",
    "Export", "Error", "Failed", "Loading", "Bold", "Italic", "Underline",
    "Light", "Dark", "Appearance", "Sidebar", "Preview", "Search", "Find",
    "Save", "Welcome", "Move", "Outline",
    "Abbrechen", "Schließen", "Löschen", "Speichern", "Teilen", "Dokument",
    "Vorlage", "Fehler",
}
SHELL_ALLOW_TEXT = {"Typst Editor", ".typ", ".pdf", ".png", ".svg"}


DOTTED_KEY = re.compile(r"[a-z]\w*\.[A-Za-z][\w.]*\Z")
PARAM = re.compile(r"\{(\w+)\}")


def load_dicts() -> tuple[dict[str, set[str]], dict[str, set[str]],
                          dict[str, dict[str, str]], list[str]]:
    keys: dict[str, set[str]] = {lang: set() for lang in LANGS}
    areas: dict[str, set[str]] = {lang: set() for lang in LANGS}
    values: dict[str, dict[str, str]] = {lang: {} for lang in LANGS}
    errors: list[str] = []

    def walk(node: object, prefix: str, lang: str, src: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{k}" if prefix else str(k), lang, src)
        elif isinstance(node, str):
            keys[lang].add(prefix)
            values[lang][prefix] = node
            if node == "":
                errors.append(f"{src}: key '{prefix}' has an empty value")
        else:
            errors.append(f"{src}: key '{prefix}' is not a string")

    for lang in LANGS:
        base = I18N / lang
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.json")):
            src = str(p.relative_to(WEB))
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except ValueError as e:
                errors.append(f"i18n: invalid JSON in {src}: {e}")
                continue
            areas[lang].add(p.stem)
            walk(data, p.stem, lang, src)
    return keys, areas, values, errors


REGEX_AFTER = set("(,=:[!&|?{};+-*%<>^~")


def tokenize_line(line: str) -> tuple[list[tuple[int, int, str]], str]:
    """Split one JS line into string literals (start, end, quote) plus the
    code without // comments. Understands ' " ` strings and /regex/ (with
    classes), so // inside either never starts a comment."""
    lits: list[tuple[int, int, str]] = []
    out: list[str] = []
    i, n = 0, len(line)
    prev_sig = ""  # last significant char (for regex-vs-division)
    in_class = False

    def push_code(j: int) -> None:
        out.append(line[j])

    while i < n:
        c = line[i]
        if c in "'\"`":
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == c:
                    break
                if c != "`" and line[j] == "\n":
                    break
                j += 1
            end = min(j + 1, n) if j < n and line[j] == c else j
            lits.append((i, end, c))
            out.append(line[i:end])
            prev_sig = "s"  # a finished string value
            i = end
            continue
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break  # line comment: cut
        if c == "/" and i + 1 < n and line[i + 1] == "*":
            j = line.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c == "/" and (prev_sig == "" or prev_sig in REGEX_AFTER):
            # regex literal: consume to closing / (classes + escapes aware)
            j = i + 1
            in_class = False
            while j < n:
                d = line[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "[":
                    in_class = True
                elif d == "]":
                    in_class = False
                elif d == "/" and not in_class:
                    break
                j += 1
            end = min(j + 1, n)
            out.append(line[i:end])
            # flags (gimsuy) belong to the regex, not to code
            while end < n and line[end] in "gimsuy":
                out.append(line[end])
                end += 1
            prev_sig = "r"
            i = end
            continue
        out.append(c)
        if not c.isspace():
            prev_sig = c
        i += 1
    return lits, "".join(out)


def strip_line_comment(line: str) -> str:
    return tokenize_line(line)[1]


def check_js(findings: list[str], known: set[str], areas_en: set[str],
             dotted: set[str]) -> None:
    for path in JS_FILES:
        if path.name in SKIP_FILES:
            continue
        rel = path.relative_to(WEB)
        lines = path.read_text(encoding="utf-8").splitlines()
        for ln, raw in enumerate(lines, 1):
            if URL_LINE.search(raw):
                continue
            lits, line = tokenize_line(raw)
            if not line.strip():
                continue
            if any(rx.search(line) for rx in SKIP_LINE_RES):
                continue
            t_spans = [(m.start(), m.end()) for m in T_CALL.finditer(line)]
            for m in T_CALL.finditer(line):
                key = m.group(2)
                if key not in known:
                    findings.append(f"{rel}:{ln}: t('{key}') has no entry")
            for start, end, quote in lits:
                if T_FIRSTARG.search(raw[:start]):
                    continue  # the key itself
                lit = raw[start:end]
                if quote == "`" and "${" in lit:
                    continue  # interpolated template: code, not prose
                body = lit[1:-1] if len(lit) >= 2 and lit[-1] == quote else lit[1:]
                val = body.replace("\\\\", "\x00")
                val = (val.replace("\\'", "'").replace('\\"', '"')
                       .replace("\\n", "\n").replace("\\t", "\t"))
                val = re.sub(r"\\u([0-9a-fA-F]{4})",
                             lambda m: chr(int(m.group(1), 16)), val)
                val = val.replace("\x00", "\\")
                stripped = re.sub(r"<[^>]*>", "", val)
                if DOTTED_KEY.match(val) and val.split(".")[0] in areas_en:
                    dotted.add(val)  # key by reference, e.g. SECS labelKeys
                    continue
                if val in ALLOW_EXACT or stripped in ALLOW_EXACT:
                    continue
                if any(rx.search(val) or rx.search(stripped) for rx in ALLOW_RES):
                    continue
                if not LETTER.search(stripped):
                    continue
                prefix = raw[:start]
                if (EL_CLASS.search(prefix) or CALL_ARG.search(prefix)
                        or CMP_PREFIX.search(prefix)):
                    continue  # class / selector / id / event / tag / comparison
                if re.search(r"\s", stripped):
                    findings.append(f"{rel}:{ln}: hardcoded string {lit[:70]}")
                elif stripped in FORBIDDEN_SINGLE:
                    findings.append(f"{rel}:{ln}: hardcoded string {lit[:70]}")


class ShellScan(HTMLParser):
    def __init__(self, known: set[str], findings: list[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.known = known
        self.findings = findings
        self.stack: list[tuple[str, bool]] = []  # (tag, i18n-covered)
        self.in_body = False
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self.in_body = True
        if not self.in_body:
            return
        if tag in ("script", "style"):
            self.skip += 1
            self.stack.append((tag, True))
            return
        d = dict(attrs)
        if tag in VOID:
            pass  # void elements have no text children; attrs checked below
        else:
            covered = self.stack[-1][1] if self.stack else False
            if d.get("data-i18n") in self.known or d.get("data-i18n-html") in self.known:
                covered = True
            else:
                for a in ("data-i18n", "data-i18n-html", "data-i18n-ph",
                          "data-i18n-title", "data-i18n-aria"):
                    v = d.get(a)
                    if v is not None and v not in self.known:
                        self.findings.append(
                            f"index.shell.html:{self.getpos()[0]}: {a}='{v}' has no entry")
            self.stack.append((tag, covered))
        for a, twin in (("placeholder", "data-i18n-ph"), ("title", "data-i18n-title"),
                        ("aria-label", "data-i18n-aria"), ("alt", "data-i18n-aria")):
            v = d.get(a)
            if v and LETTER.search(v) and (re.search(r"\s", v) or v in FORBIDDEN_SINGLE):
                if d.get(twin) not in self.known and v not in SHELL_ALLOW_TEXT:
                    self.findings.append(
                        f"index.shell.html:{self.getpos()[0]}: <{tag}> {a}='{v[:50]}' lacks {twin}")

    def handle_endtag(self, tag: str) -> None:
        if not self.in_body:
            return
        if tag == "body":
            self.in_body = False
        if self.stack:
            top = self.stack.pop()
            if top[0] in ("script", "style"):
                self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.in_body or self.skip or not self.stack:
            return
        txt = data.strip()
        if not txt or not re.search(r"[A-Za-zäöüÄÖÜß]{3}", txt):
            return
        if self.stack[-1][1]:
            return  # covered by data-i18n on self or an ancestor
        if txt in SHELL_ALLOW_TEXT:
            return
        tag = self.stack[-1][0]
        self.findings.append(
            f"index.shell.html:{self.getpos()[0]}: <{tag}> text '{txt[:50]}' lacks data-i18n")


def main() -> int:
    keys, areas, values, errors = load_dicts()
    findings: list[str] = list(errors)
    known = keys["en"] | keys["de"]
    for lang in LANGS:
        other = LANGS[1] if lang == LANGS[0] else LANGS[0]
        for key in sorted(keys[lang] - keys[other]):
            findings.append(f"web/i18n/{other}/{key.split('.')[0]}.json: key '{key}' missing in {other}")
    for a, b in (("en", "de"), ("de", "en")):
        for key in sorted(keys[a] & keys[b]):
            pa, pb = set(PARAM.findall(values[a][key])), set(PARAM.findall(values[b][key]))
            if pa != pb:
                findings.append(f"web/i18n/{b}/{key.split('.')[0]}.json: key '{key}' params differ "
                                f"({a}: {sorted(pa)} vs {b}: {sorted(pb)})")
    # unknown area (typo guard): first segment must be an existing area file
    for key in sorted(known):
        area = key.split(".")[0]
        if area not in areas["en"]:
            findings.append(f"i18n key '{key}': unknown area '{area}' (no web/i18n/en/{area}.json)")
    # every used key must exist in BOTH languages
    used: set[str] = set()
    for path in JS_FILES:
        for m in T_CALL.finditer(path.read_text(encoding="utf-8")):
            used.add(m.group(2))
    shell_src = SHELL.read_text(encoding="utf-8")
    for m in I18N_ATTR.finditer(shell_src):
        used.add(m.group(2))
    dotted: set[str] = set()
    check_js(findings, known, areas["en"], dotted)
    for key in sorted(dotted):
        used.add(key)
        for lang in LANGS:
            if key not in keys[lang]:
                findings.append(f"web/i18n/{lang}/{key.split('.')[0]}.json: key '{key}' missing in {lang}")
    for key in sorted(used):
        for lang in LANGS:
            if key not in keys[lang]:
                findings.append(f"web/i18n/{lang}/{key.split('.')[0]}.json: key '{key}' missing in {lang}")
    ShellScan(known, findings).feed(shell_src)
    # report unused keys as warnings (no fail: shared fallbacks stay valid)
    unused = sorted(known - used)
    if findings:
        print(f"check_i18n: {len(findings)} finding(s):")
        for f in sorted(set(findings)):
            print(f"  {f}")
        return 1
    if unused:
        print(f"check_i18n: clean ({len(known)} keys en+de); {len(unused)} unused key(s): "
              + ", ".join(unused[:10]) + (" ..." if len(unused) > 10 else ""))
    else:
        print(f"check_i18n: clean ({len(known)} keys en+de)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
