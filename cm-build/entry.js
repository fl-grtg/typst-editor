// Rebuild: cd cm-build && npm ci && npm run build (writes ../vendor-cm.js).
// CI job "vendor-bundle" rebuilds and fails on diff or > 600KB.
// One bundle, one instance per package: no CDN, no duplication problem.
export { EditorView, minimalSetup } from "codemirror";
export { indentMore, indentLess } from "@codemirror/commands";
export { Compartment, EditorState, StateField, StateEffect, RangeSet, Prec } from "@codemirror/state";
export { hoverTooltip, keymap, Decoration, WidgetType, lineNumbers, gutterLineClass, GutterMarker } from "@codemirror/view";
export { autocompletion, startCompletion, acceptCompletion, currentCompletions, closeCompletion, moveCompletionSelection, closeBrackets, snippetCompletion, nextSnippetField, prevSnippetField } from "@codemirror/autocomplete";
export { typst_lezer, typstBuiltinSignatures, typstGlobalCompletions, typstMathCompletions, typstParser } from "codemirror-lang-typst/lezer";
export { linter, lintGutter, setDiagnostics, forEachDiagnostic } from "@codemirror/lint"; // F1: compiler errors via lint (F20 column ranges); resolved from the transitive pin (codemirror/codemirror-lang-typst, lock 6.9.7) — no direct dep, so package-lock stays untouched
// Theme overrides: @codemirror/language + @lezer/highlight are pinned as direct
// deps (package.json + lock) so `npm ci` keeps a single copy. Allows a var-driven
// HighlightStyle in index.html that beats the vendored Typst defaults.
export { syntaxHighlighting, HighlightStyle, foldGutter, foldKeymap, bracketMatching, indentUnit } from "@codemirror/language";
export { tags } from "@lezer/highlight";
export { typstTags } from "codemirror-lang-typst/lezer";
