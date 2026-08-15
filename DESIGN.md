# Design system — *Modernist*

The visual language of **Taller de Rotulación**, ported from the
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
floating toolbar covers the very thing the user is working on. The
abandoned attempt at one (`floating_bar.py`) has been deleted.

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

`NEUTRAL_*` and `ACCENT_*` are the two ramps. Only the rungs something
actually uses are declared — an unused colour is a decision nobody has
made yet, not a gap to fill:

| Token | Used for |
| --- | --- |
| `NEUTRAL_100` | zebra stripe in the translation table |
| `NEUTRAL_300` | button hover, meter track, `neutral` tag fill |
| `NEUTRAL_400` | button pressed, dashed drop-zone border |
| `NEUTRAL_500` | disabled text, a pending step's chip, the rail's scrollbar thumb |
| `NEUTRAL_600` | kickers, secondary/hint text |
| `NEUTRAL_700` | body text on the rail |
| `NEUTRAL_900` | the dark canvas, via `CANVAS_BG` |
| `ACCENT_100/200` | tinted backgrounds — table selection, `accent` tag |
| `ACCENT_600/700` | button hover / pressed on `primary`; error text |
| `ACCENT_800` | text on a low-confidence row; the darkest mark colour |

**Never mix a neutral into an accent role, or the reverse.** A muted dot
means "engine missing"; the red is spent on the card that says what to do
about it, not on the dot.

### Semantic names

Three names are **not** aliases of a token — they say what the colour
*means*, which the token name alone does not:

| Name | Value | Means |
| --- | --- | --- |
| `BTN_FG` | `#ffffff` | text on a filled accent button |
| `ERROR_COLOR` | `ACCENT_700` | something went wrong |
| `SUCCESS_COLOR` | `COLOR_ACCENT` | something completed |

Everything else uses the token names directly. The old `BG_COLOR` /
`FG_COLOR` / `PANEL_BG` / `BTN_BG` aliases from the port are gone.

### The one deliberate exception

`TranslatorCanvas`'s on-canvas text editor
([`translator_canvas.py`](src/views/translator_canvas.py)) is **pure
white with pure black text**, not `COLOR_BG` on `COLOR_TEXT`. That is on
purpose: while you are typing, the editor stands in for the finished
page, and the page is white. Do not "fix" it to the palette.

The exception covers the two colours and nothing else — its font is
`theme.body_font(10)` like any other widget, because you are typing into
the interface even if what you see previews the page.

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
| Footer status bar | 2 px rule + one padded line | `toolbar.StatusBar` |
| Rail section padding | 12 px | `SIDEBAR_SECTION_PAD` |
| Structural rule | 2 px | `theme.rule(thickness=2)` |
| Inner divider | 1–2 px, `COLOR_DIVIDER` | `theme.rule(color=…)` |
| Meter | 6 px (4 px for the step-2 progress band) | `theme.Meter(height=…)` |
| Tooltip delay | 450 ms | `TOOLTIP_DELAY_MS` |

Fixed-width panels need `pack_propagate(False)`, or Tk shrinks the frame
to fit its children and the rail collapses.

> **Note.** Padding is written as literals. A `SPACE_1…SPACE_8` scale
> used to sit in `config.py` unused by anything and has been removed. If
> you want a spacing scale, adopt it everywhere in one pass — a scale
> that half the views ignore is a third convention, not a system.

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
│ ─────────  │  StatusBar — status left, shortcuts right       │
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

### Controls

| Factory | What it is |
| --- | --- |
| `button(...)` | the five variants — see §7 |
| `SegmentedBar` | a bordered strip where exactly one option is active |
| `option_menu` | a dropdown; `indicatoron=False`, so it reads as a flat field |
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
| `StatusBar` (in `toolbar.py`) | the footer: `set(text, level)` for status, `set_hint()` for shortcuts |
| `Tooltip` (in `toolbar.py`) | 450 ms delay; `button(tooltip=…)` wires it for you |
| `alert(master, title, message, level=)` | says something and waits for the acknowledgement |
| `confirm(master, title, message, confirm_label=)` | asks; `True` only for the confirming button |

`alert` and `confirm` are the **same modal**, differing by one button —
see §8. Never `tkinter.messagebox`: it draws the operating system's own
dialog, with its font, its icons and its «Aceptar / Cancelar». The one
exception is `app.messagebox_safe`, which keeps the native box
underneath as a floor for errors that fire before there is a window to
paint a dialog on.

`toolbar.py` holds only those two. Its old button factories
(`make_button`, `make_color_swatch`, `ToolbarBar`…) predate this design
system and have been deleted — `theme.py` is the only vocabulary.

---

## 7. Buttons

Four variants. Picking the wrong one is the most common way to make a
screen look off, so this is the decision table:

| Variant | Looks like | Use for |
| --- | --- | --- |
| `outline` | ink border, transparent fill | **the default.** Any real, pressable action |
| `primary` | filled accent, white text | **the one action** that advances the step. One per screen |
| `ink` | filled ink, paper text | a toggle that is currently **on** |
| `ghost` | no border, accent text | destructive or "escape hatch" text actions (used once) |

Weight is `border_width`: 1 px on its own, 2 px next to a `SegmentedBar`
so the button matches the strip beside it.

### The Windows border trap

**Windows never paints a `tk.Button`'s `highlightthickness` ring.**

There used to be a fifth variant, `secondary`, which drew its border
that way — so on Windows it rendered as *plain text with no border*. It
was documented as «only inside a container that already has its own
edge», and then used on nine buttons, none of which was inside one. It
has been deleted rather than re-documented: a rule violated everywhere
it applies is not a rule, and the trap is easier to close than to
remember. `outline` draws its border with `relief="solid"` + `bd`, which
Windows does paint.

> **Rule:** there is no borderless-on-Windows variant left to reach for.
> An unknown variant name falls back to `outline`, and `test_smoke.py`
> fails if any `variant="…"` in `src/` names something that is not in
> `_VARIANTS`.

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

### Modal or status bar

A modal stops the work; the status bar does not. So the rule is not the
severity of the message but whether an answer is needed:

- **It needs an answer** (`confirm`) — a modal, always. It blocks because
  the code after it depends on the answer.
- **It only tells** — the status bar, whenever the screen has one. Every
  step's view does; `home_view` does not, which is the only reason its
  four messages are `alert`.
- **The exception: a button whose whole outcome is «nothing to do».**
  Step 3's «Descargar par» with the pair already installed answers with
  an `alert`, bar or no bar. The status bar narrates what is happening;
  it does not answer a click, and a download button that downloads
  nothing and says so in a footer line reads as broken.

An `alert` next to a `StatusBar` is almost always the message being said
twice. The button of a `confirm` is `primary` — the accent is already
the colour of consequence in this app, so a destructive action needs no
variant of its own, only a label that says what it does (§7).

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
- **`bind_all` writes to the `all` tag, which holds one script per
  sequence.** Two owners cannot share it: the second one silently
  replaces the first, and "save the old script and put it back later" is
  a trap — the script it restores may name a Tcl command Tk deleted when
  the widget that owned it died. The wheel has exactly one owner, the
  rail (`Sidebar._on_wheel`), which routes by pointer position and hands
  the event to whatever the active view registered with
  `set_wheel_client`.
- **On Windows, Tk 8.6 delivers `<MouseWheel>` to the widget with
  keyboard focus**, not the one under the pointer. A wheel binding on a
  canvas that never takes focus may never fire. This is why the rail
  routes by pointer position instead of trusting delivery.
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
