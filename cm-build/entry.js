// Rebuild: cd cm-build && npm ci && npm run build (writes ../vendor-cm.js).
// CI job "vendor-bundle" rebuilds and fails on diff or > 600KB.
// One bundle, one instance per package: no CDN, no duplication problem.
export { EditorView, minimalSetup } from "codemirror";
export { indentMore, indentLess } from "@codemirror/commands";
export { Compartment, StateField, StateEffect, RangeSet } from "@codemirror/state";
export { hoverTooltip, keymap, Decoration, WidgetType, lineNumbers, gutterLineClass, GutterMarker } from "@codemirror/view";
export { autocompletion, startCompletion, acceptCompletion, currentCompletions, closeCompletion, moveCompletionSelection, closeBrackets } from "@codemirror/autocomplete";
export { typst_lezer, typstBuiltinSignatures } from "codemirror-lang-typst/lezer";
export { forEachDiagnostic } from "@codemirror/lint"; // read lint diagnostics (fast, good messages)
