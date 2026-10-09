"""Starter document content shown to new users."""
from __future__ import annotations

TUTORIAL = """\
// Short Typst example paper (fits on one A4 page)

#set page(paper: "a4", margin: (x: 2.2cm, y: 1.8cm), numbering: "1")
#set text(font: "New Computer Modern", size: 11pt)
#set par(justify: true)
#set heading(numbering: "1.")

#align(center)[
  #text(15pt, weight: "bold")[A Short Example Paper in Typst]

  #v(0.5em)
  Alice Example · Bob Typst

  #v(0.2em)
  #text(9.5pt)[Department of Computer Science · Example University]
]

#v(0.8em)

#align(center)[Abstract]
This short document demonstrates the main Typst features needed for a paper: headings, paragraphs, mathematics, a table, a simple diagram and a code snippet.

= Introduction
Typst is a modern typesetting system. You write text normally. \\
Italic and bold work directly.

Here is a small code example:

#let greet(name) = [Hello, #name!]
#greet("World")

= Mathematics
Inline math: $E = m c^2$.

Display math:
$
  integral_0^infinity e^(-x^2) dif x = sqrt(pi)/2
$

= Table and Diagram

#figure(
  table(
    columns: 3,
    align: (left, center, right),
    stroke: 0.5pt,
    inset: 5pt,
    [Name], [Value], [Unit],
    [Speed of light], [$c$], [$3 times 10^8$ m/s],
    [Planck constant], [$h$], [$6.626 times 10^(-34)$ J·s],
  ),
  caption: [Fundamental constants.],
)

// Centered bar diagram with dark gray bars
#figure(
  align(center)[
    #let data = (
      ("A", 40),
      ("B", 65),
      ("C", 30),
      ("D", 80),
    )
    #let max-h = 2.2cm
    #let bar-w = 1.1cm
    #let gap = 0.45cm

    #box(width: 7.2cm, height: 3.1cm)[
      #for (i, (label, value)) in data.enumerate() {
        let h = max-h * (value / 100)
        place(
          left + bottom,
          dx: 0.6cm + i * (bar-w + gap),
          dy: -0.35cm,
          rect(
            width: bar-w,
            height: h,
            fill: luma(70),
            stroke: 0.5pt + luma(40),
            radius: 2pt,
          )
        )
        place(
          left + bottom,
          dx: 0.75cm + i * (bar-w + gap),
          dy: -h - 0.55cm,
          text(8pt)[#value]
        )
        place(
          left + bottom,
          dx: 0.9cm + i * (bar-w + gap),
          dy: -0.05cm,
          text(9pt)[#label]
        )
      }
      #place(
        left + bottom,
        dx: 0.4cm,
        dy: -0.35cm,
        line(length: 6.4cm, stroke: 0.6pt)
      )
    ]
  ],
  caption: [Simple bar diagram created with pure Typst.],
)

= Conclusion
This example shows the essential Typst syntax and fits on a single A4 page.
"""
