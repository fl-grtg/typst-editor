// Ein Bundle, eine Instanz pro Paket: kein CDN-, kein Doppel-Problem.
export { EditorView, minimalSetup } from "codemirror";
export { indentMore, indentLess } from "@codemirror/commands";
export { Compartment, StateField, StateEffect, RangeSet } from "@codemirror/state";
export { hoverTooltip, keymap, Decoration, WidgetType, lineNumbers, gutterLineClass, GutterMarker } from "@codemirror/view";
export { autocompletion, startCompletion, acceptCompletion, currentCompletions, closeCompletion, moveCompletionSelection, closeBrackets } from "@codemirror/autocomplete";
export { typst_lezer } from "codemirror-lang-typst/lezer";
export { forEachDiagnostic } from "@codemirror/lint"; // Lint-Fehler lesen (schnell, gute Texte)
