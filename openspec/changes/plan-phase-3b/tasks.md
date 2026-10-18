# Tasks

## 1. Two-column structures

- [ ] 1.1 The DOM collector reads `Label: value` lines and repeated sibling label/value pairs besides rows and `dl`
      groups, within the main region (else the body) outside tangential content; a field given several values by
      lines or sibling pairs is dropped.

## 2. Typed spotting

- [ ] 2.1 The collector spots a money field's or a checked identifier's one shown value in the main region with the
      item layer's helpers (`collect/items/spot.py`, moved out of `align.py`).

## 3. Delete what this supersedes

- [ ] 3.1 Delete the whole-document row and `dl` reading and its helpers in `collect/dom.py`.
