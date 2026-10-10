#set page(paper: "a4", margin: 2cm)
#set text(size: 11pt)
#set heading(numbering: "1.")

= Introduction

This   is   a   sample   with   messy   spacing.

== Background

- first point
- second    point
+ numbered one
+ numbered two

#let x = 1
#let y = x + 2

The value is #x and #y.

= Methods

#table(
  columns: (1fr, 1fr),
  [*Name*], [*Value*],
  [x], [#str(y)],
)

$ sum_(i=0)^n x_i = (n*(n+1))/2 $

#figure(caption: [A   captioned   figure])[
  #rect(width: 3cm, height: 1cm, fill: blue)
] <fig:demo>

See @fig:demo.
