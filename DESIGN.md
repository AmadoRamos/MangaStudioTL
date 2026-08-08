# Design system — *Modernist*

The visual language of **Visor de Manga y Webcomic**, ported from the
`Traductor de Manga - Mockups` canvas (direction 3a) onto Tk.

This document is for anyone touching the interface. It says what the
parts are, which one to reach for, and why several of them are built the
way they are. It does **not** describe what each step does — that is
[README.md](README.md).

Two files are the source of truth, and this document only explains them:

| File | Holds |
| --- | --- |
| [`src/config.py`](src/config.py) | the tokens — colour, metrics, defaults |
| [`src/views/theme.py`](src/views/theme.py) | the vocabulary — every widget factory |

If a screen needs a colour or a control that is not in one of those two,
the fix is to add it there, not to hard-code it in the view. That is the
whole reason the four steps read as one application.

---

## 1. Principles

**Rules, not boxes.** Structure is drawn with lines, not with borders
around everything. 2 px ink for a structural edge (the top bar, the rail,
a segmented control); 1 px divider for a separation *inside* a panel. No
rounded corners. No drop shadows on flat surfaces.

**One accent.** Red (`#ec3013`) is spent on four things only: the active
step, the primary action, the marks on the page, and anything asking for
review. If everything is accented, the eye has nowhere to go. When
something needs emphasis but is not one of those four, use ink.

**Kickers name regions.** A small uppercase label (`MARCAS`, `SECCIÓN
SELECCIONADA`, `HERRAMIENTAS`) is how a block is titled — not a bigger,
heavier heading. Headings are for a screen's own voice, and there is
roughly one per screen.

**The page is the brightest thing on screen.** The scan always sits on
`CANVAS_BG` (`#2d2b2b`). The shell is paper-coloured; the work is not.
This is what makes a manga page readable next to a light UI.

**Nothing floats over the canvas.** Every control lives in a docked strip
— the top bar, the rail, the right-hand tool dock, the footer. A
floating toolbar covers the very thing the user is working on.
(`floating_bar.py` is the abandoned attempt; nothing imports it.)

---

## 2. Colour

### Core tokens

| Token | Hex | Role |
| --- | --- | --- |
| `COLOR_BG` | `#f3f2f2` | paper — the shell background |
| `COLOR_SURFACE` | `#eae9e9` | a raised-but-flat area: the rail, the dock, input fields |
| `COLOR_TEXT` | `#201e1d` | ink — body text, structural edges, the "on" state |
| `COLOR_ACCENT` | `#ec3013` | the one accent |
| `COLOR_DIVIDER` | `#9f9d9d` | separation inside a panel |
| `CANVAS_BG` | `#2d2b2b` | the dark canvas the page sits on (`NEUTRAL_900`) |

`COLOR_DIVIDER` is 40 % ink over paper, **flattened to an opaque hex** —
Tk has no alpha on widget borders, so the blend has to be baked in.

### Ramps

`NEUTRAL_100…900` and `ACCENT_100…800` are the two ramps. In practice
only a handful carry weight:

| Token | Used for |
| --- | --- |
| `NEUTRAL_300` | button hover, meter track, `neutral` tag fill |
| `NEUTRAL_400` | button pressed, dashed drop-zone border |
| `NEUTRAL_500` | disabled text, a pending step's chip, the rail's scrollbar thumb |
| `NEUTRAL_600` | kickers, secondary/hint text |
| `NEUTRAL_700` | body text on the rail |
| `ACCENT_100/200` | tinted backgrounds — table selection, `accent` tag |
| `ACCENT_600/700` | button hover / pressed on `primary`; error text |

**Never mix a neutral into an accent role, or the reverse.** A muted dot
means "engine missing"; the red is spent on the card that says what to do
about it, not on the dot.

### Legacy aliases

`BG_COLOR`, `FG_COLOR`, `PANEL_BG`, `BTN_BG`… still exist and are used in
~58 places. They are aliases of the tokens above, kept so nothing broke
during the port. **New code uses the token names.**

---

## 3. Typography

Three stacks, resolved **once at runtime** by `theme.init(root)` against
what is actually installed — Tk silently substitutes a missing family, so
the stack is walked explicitly and the first hit wins.

| Stack | First choice | Fallback |
| --- | --- | --- |
| heading | `Archivo` (the mockups' typeface) | `Segoe UI` |
| body | `Archivo` | `Segoe UI` |
| mono | `Cascadia Mono` | `Courier New` |

`theme.init()` **must run after the Tk root exists and before any widget
is built.** It also themes the ttk widgets (§9).

### Sizes in use

| Call | Size | Where |
| --- | --- | --- |
| `heading_font(8)` | 8 bold | kickers, tags, segmented-bar labels, table headings |
| `heading_font(9–10)` | 9–10 bold | buttons, step labels |
| `heading_font(17)` | 17 bold | a screen's heading — one per screen |
| `body_font(8–9)` | 8–9 | hints, consequence lines, engine status |
| `body_font(10)` | 10 | body text, table rows, inputs |

Buttons use the **heading** stack, not the body stack: a label that has
to be pressed reads better with the tighter grotesque.

---

## 4. Metrics

The numbers that hold the layout together. All of them are constants —
if you find yourself typing one of these into a view, use the constant.

| Metric | Value | Constant |
| --- | --- | --- |
| Window | 1400 × 850, min 1000 × 640 | `WINDOW_*` |
| Left rail | 260 px, fixed | `SIDEBAR_WIDTH` |
| Right tool dock (step 2) | 186 px, fixed | `TOOLS_DOCK_WIDTH` |
| Top bar | 42 px + 2 px rule | `theme.TopBar(height=…)` |
| Footer hint bar | 36 px + 2 px rule | `theme.HintBar` |
| Rail section padding | 12 px | `SIDEBAR_SECTION_PAD` |
| Structural rule | 2 px | `theme.rule(thickness=2)` |
| Inner divider | 1–2 px, `COLOR_DIVIDER` | `theme.rule(color=…)` |
| Meter | 6 px (4 px for the step-2 progress band) | `theme.Meter(height=…)` |
| Tooltip delay | 450 ms | `TOOLTIP_DELAY_MS` |

Fixed-width panels need `pack_propagate(False)`, or Tk shrinks the frame
to fit its children and the rail collapses.

> **Note.** `SPACE_1…SPACE_8` (4/8/12/16/24/32) are declared in
> `config.py` and **used nowhere** — padding is currently written as
> literals. Either adopt the scale or drop the tokens; do not add a third
> convention.

---

## 5. The shell

Every step is the same frame:

```
┌────────────┬─────────────────────────────────────────────────┐
│ PASO n DE 4│  TopBar — segmented controls, 42 px             │
│ ┌────────┐ ├─────────────────────────────────────────────────┤
│ │n  Paso │ │                                      ┌─────────┐│
│ └────────┘ │  Dark canvas with the page           │ tool    ││
│            │                                      │ dock    ││
│ [sections  │                                      │ (step 2)││
│  of the    │                                      └─────────┘│
│  step]     ├─────────────────────────────────────────────────┤
│ ─────────  │  HintBar — status left, shortcuts right         │
│ [ACTION →] └─────────────────────────────────────────────────┘
│  consequence
└────────────┘
```

Four rules govern it:

1. **Controls dock, they never float.** Canvas controls go in the top
   bar as segmented strips; tools that the hand returns to while working
   go in the right-hand dock, against the page.
2. **The primary action is anchored to the foot of the rail**, with one
   line under it saying what pressing it will do. `sidebar.set_footer()`
   packs it to `side=BOTTOM` *before* the scrolling section area is
   built, so a long mark list can never push it off screen.
3. **The rail shows one step: the current one.** The header reads
   `PASO n DE 4` and only that step's row is packed. The other three
   rows are built and kept alive but unpacked — `set_step_indicator` is
   a `pack`/`pack_forget`, so switching steps re-measures nothing.
4. **The rail's middle band scrolls, the ends do not.** A chapter's mark
   list outruns 850 px; the step header and the footer action must not
   move when it does. The scrollbar appears only on overflow, and the
   rail takes the mouse wheel only while the pointer is over it —
   handing the previous binding back on the way out, because the canvas
   views bind the wheel application-wide.

---

## 6. Component vocabulary

Everything in `theme.py`. Build with these; do not instantiate a raw
`tk.Button` or `tk.Label` in a view.

### Text

| Factory | What it is |
| --- | --- |
| `kicker(parent, text)` | uppercase region label, 8 bold, `NEUTRAL_600`. Uppercasing is automatic — pass normal case |
| `heading(parent, text)` | the screen's own title, 17 bold |
| `body(parent, text, size=, fg=, wrap=)` | everything else |
| `field_label(parent, text)` | the label above an input, 9 |
| `rule(parent, thickness=, color=, vertical=)` | a structural line |
| `spacer(parent)` | flexible gap that pushes what follows to the bottom |

### Controls

| Factory | What it is |
| --- | --- |
| `button(...)` | the five variants — see §7 |
| `SegmentedBar` | a bordered strip where exactly one option is active |
| `option_menu` / `set_option_values` | a dropdown; `indicatoron=False`, so it reads as a flat field |
| `slider(from_, to, variable)` | value hidden (`showvalue=False`) — show it yourself in the label if it matters |
| `checkbox(text, variable)` | |
| `entry` / `text_area` | 1 px divider border that turns **accent on focus**; the caret is accent too |
| `swatch(color, command, selected=)` | a colour square; selection is an accent ring around it, never a checkmark |

### Blocks and feedback

| Factory | What it is |
| --- | --- |
| `card(border=, border_width=)` | a bordered block — recent chapters, engine status |
| `tag(text, kind=)` | a compact chip. `neutral` \| `accent` \| `solid` \| `ink` |
| `Meter(height=, color=)` | a progress rule: neutral track, solid fill, no text |
| `DashedZone` | a dashed-border drop area (§9) |
| `TopBar` | the 42 px strip + its rule; children go in `.body`, `.gap()` pushes the rest right |
| `HintBar` | the footer: `set_left()` for status, `set_right()` for shortcuts |
| `StatusBar` (in `toolbar.py`) | the older footer, same shape, with levels |
| `Tooltip` (in `toolbar.py`) | 450 ms delay; `button(tooltip=…)` wires it for you |

---

## 7. Buttons

Five variants. Picking the wrong one is the most common way to make a
screen look off, so this is the decision table:

| Variant | Looks like | Use for |
| --- | --- | --- |
| `primary` | filled accent, white text | **the one action** that advances the step. One per screen |
| `ink` | filled ink, paper text | a toggle that is currently **on** |
| `outline` | ink border, transparent fill | a real, pressable action sitting in a strip or dock |
| `secondary` | divider border, transparent fill | a low-weight action inside a panel that already has its own border |
| `ghost` | no border, accent text | destructive or "escape hatch" text actions (used once) |

### The Windows border trap

**Windows never paints a `tk.Button`'s `highlightthickness` ring.**

`secondary` draws its border with `highlightthickness`, so on Windows it
renders as *plain text with no border*. That is fine inside a card, whose
own edge already frames it — but on its own strip it stops reading as
something you can press. This has been reported as a bug twice.

`outline` exists for exactly that case: it draws the border with
`relief="solid"` + `bd`, which Windows does paint.

> **Rule:** a button standing on its own — in a top bar, in the tool
> dock, next to a `SegmentedBar` — is `outline`. `secondary` is only for
> buttons inside a bordered container.

### Toggles

A toggle flips **`outline` ⇄ `ink`** via `theme.restyle_button(btn,
variant)`, which keeps the widget's geometry (and its border weight — it
reads back `_border_width` so restyling never quietly thins the border).

Two consequences for anyone building a panel of toggles:

- `restyle_button` mutates in place, so **the reference must stay valid**.
  If your section is destroyed and rebuilt on every state change, the
  toggles have to live somewhere that isn't. This is why the step-2 tool
  dock is built once in `_build_ui` and only `pack_forget`/`pack`-ed,
  while the rail sections around it are torn down and recreated freely.
- The label changes with the state (`Editar` → `Editando`, `Ocultar` →
  `Mostrar`), so the button says what *is*, not only what it does.

---

## 8. State and feedback

### Segmented bars

The canvas controls in every step: view mode, zoom, clean/original, page
nav, the step-3 filters.

- Active segment = **filled ink**. Not accent — the accent belongs to the
  primary action, and a bar has one active item at all times, which would
  put red permanently on screen.
- `uniform_chars=theme.SEGMENT_CHARS` (9) gives every labelled segment
  the same width, so `Una` and `Original` line up across the bar.
- **The width only ever grows.** The step-3 filters carry counts that
  change as the chapter is translated; a strip that reflowed each time a
  number gained a digit would twitch under the cursor.
- A segment that is a *readout* rather than a label (`42 %`, `1 / 2`)
  passes an explicit `width=` and is pinned out of the uniform sizing,
  so the strip does not shuffle when `100%` becomes `1000%`.
- Icon-only strips (`− +`, `◀ ▶`) leave `uniform_chars` at 0 and stay as
  tight as their glyphs.

### Progress

`Meter` is the only progress indicator. No spinners, no indeterminate
bars — every long operation in this app knows its total.

- Accent fill for work the user is waiting on.
- Ink fill for background work they are not waiting on (the rail's
  `Limpieza · LaMa` band).
- At `0.0` the fill is *unplaced*, not zero-width, so an empty meter is
  a clean track.

### Status levels

`StatusBar.set(text, level)` takes `info` \| `working` \| `success` \|
`error`.

Note that `working` and `success` currently resolve to the **same
colour** (ink); only `error` (`ACCENT_700`) and `info` (`NEUTRAL_600`)
are visually distinct. If a screen needs to distinguish working from
done, it must do it in the wording.

### Confidence bands

OCR confidence is shown as a number plus a word: **alta** ≥ 85, **media**
≥ 60, **baja** below. The thresholds are `CONFIDENCE_HIGH` /
`CONFIDENCE_LOW` in `translation_table.py`.

Low confidence is the one case where a table row earns accent treatment
(`ACCENT_100` fill, `ACCENT_800` text) — it is a request for review. An
untranslated row is merely muted (`NEUTRAL_500` text), and the zebra
stripe is `NEUTRAL_100`. The three are mutually exclusive, in that order
of priority.

### Disabled

`disabledforeground=NEUTRAL_500` on every button. Hover handlers check
`state` before repainting, so a disabled button does not light up under
the cursor. **Prefer disabling to hiding** when an action is temporarily
unavailable and the user might look for it — hide only when the whole
region is meaningless, as the tool dock is while the OCR pass runs.

---

## 9. Tk pitfalls worth knowing

Hard-won, each one behind a bug:

- **A `tk.Button`'s highlight ring is not painted on Windows** (§7) —
  use `relief` + `bd` for a border that must show. Note this is specific
  to `Button`: `Entry` and `Text` *do* get their ring, which is how their
  focus state works.
- **Tk cannot draw a dashed widget border.** `DashedZone` paints the
  frame on a canvas and puts the content in a canvas window, re-laid on
  every `<Configure>`.
- **A collected `tkfont.Font` takes its Tcl named font with it** — and
  any canvas item still pointing at that font goes too. Font caches are
  therefore never evicted mid-draw; they are cleared only when the items
  are about to be deleted anyway (`TranslatorCanvas.set_store`).
- **ttk needs the `clam` theme** before `Treeview` and `Scrollbar` will
  accept the styling. `theme._init_ttk()` does it. Two scrollbar styles
  exist because the rail sits on the darker surface and needs more
  contrast than the table: `Rail.Vertical.TScrollbar` vs
  `Modernist.Vertical.TScrollbar`.
- **A `tk.Entry` can hold a newline** if you paste one into it. Do not
  rely on the widget type to enforce a single-line value.
- **`pack_propagate(False)`** on any frame with a fixed width or height,
  or its children resize it.
- **`before=` matters in `pack`.** Widgets that are hidden and re-shown
  (the tool dock, the clean band, a step row) must be re-packed with an
  explicit `before=`, or they come back at the bottom of the container.

---

## 10. Adding a new control

1. Is it already in `theme.py`? Use it.
2. If not, add the factory **there**, not in the view — even for a
   one-off. Consistency in this app comes from the vocabulary being
   small and shared.
3. Take colours from `config.py` tokens. If you need a new colour,
   justify it against the ramps in §2 first; nine neutrals and seven
   accents is usually enough.
4. Square corners, flat relief, ink or divider for edges.
5. Give it hover and disabled states. A control that does not react to
   the cursor does not look pressable.
6. Add a tooltip if the label is shortened or the action is
   irreversible.
7. Check it on Windows before believing the border is there.
