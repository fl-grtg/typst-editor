#let title = [My   Report]
#let authors = ("Alice", "Bob")
#align(center, text(17pt, weight: "bold", title))
#v(1em)
#align(center)[#authors.join(", ", last: ", and ")]

=Abstract
#lorem(30)

= Content

#for i in range(3) [
  Item #i: #(i * i)
]

#if true [
  Yes branch
] else [
  No branch
]

#grid(
  columns: (1fr, 1fr),
  [left   cell], [right   cell],
)
