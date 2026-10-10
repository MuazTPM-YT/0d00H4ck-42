# UI/UX audit (Apple-style redesign)

Standard: `.claude/skills/apple-design` (WWDC design foundations, materials, type, motion) and
`.claude/skills/emil-design-eng` (polish, motion decisions, review format). Installed with
`npx skills@latest add emilkowalski/skills`. Scope: every screen in `frontend/src`, desktop (1280 px), light and
dark. Date: 10 Oct 2026, branch `feat/ui-polish`.

Direction: black is the primary, white the surface, one quiet grey scale, Apple system colours only for
meaning (blue moving, green done, orange attention, red stopped). Dark mode follows the OS and inverts
(white primary on black). Large icons, plain words, 44 px touch targets, answer on press-down.

## 1. Shared design system: fixed in this preview

| Before | After | Why |
| --- | --- | --- |
| Indigo primary `#2e4a86`, indigo "weave" sidebar | Black primary `#1d1d1f`, frosted white sidebar (`material-strong`), Apple greys `#f5f5f7`/`#6e6e73` | Brief: Apple look, black then white. Translucent chrome is a floating layer, not an opaque strip (apple §12) |
| 16 px root, `text-sm` everywhere (14 px) | 17 px root (`html { font-size: 106.25% }`) | Apple body size; every rem size and gap grows, so touch targets do too, and browser text size still scales the layout (apple §15) |
| One letter-spacing for all sizes | `h1 -0.022em`, `h2/h3 -0.016em`, body `-0.006em`, optical sizing on | Tracking is size-specific (apple §15) |
| Generic font stack | `-apple-system, SF Pro, Segoe UI Variable, system-ui` | System font first: SF on Apple, Segoe UI Variable on Windows. Offline, no download |
| Button `transition-all`, no `:active`, `h-9` (36 px) | `pressable` utility: `transform 160ms cubic-bezier(.23,1,.32,1)`, `scale(.97)` on press, pill, `h-11` (47 px); `sm` grows to 47 px on touch (`pointer-coarse`) | Never `transition: all`; buttons answer on press-down; 44 px minimum (emil, apple §1) |
| Input `h-9 rounded-md`, 3 px ring | `h-11 rounded-xl`, 4 px soft halo, red halo when `aria-invalid` | Touch size, clear focus, inline error state |
| Native `select` styled 4 different ways | Base `select` rule: same radius, card fill, SF-style chevron, `min-height: 2.75rem` | One look everywhere; never below 44 px even where a screen passes `h-9` |
| Sheet `ease-in-out`, open 500 ms | iOS drawer curve `cubic-bezier(.32,.72,0,1)`, open 300 ms, close 200 ms, rounded inner edge | UI motion under 300 ms; exit faster than enter (emil) |
| Dialog zooms from 0.95 with `ease`, 16 px close target | Zoom from 0.96, `ease-out` 200 ms in / 150 ms out, 47 px round close button, frosted dim | Never from nothing; fast exit; a way out you can hit (emil, apple §12) |
| Tables `h-10`, `p-2`, ungated hover, rows mouse-only | `h-11` header, `h-14` rows, hover gated on `(hover: hover)`, rows focusable with Enter/Space | Density for office screens without hover-stick on tablets; keyboard users can open every row |
| Empty state: dashed border, 32 px icon | Calm card, 64 px icon tile, one sentence, action | Large icons, clear wording |
| Page header: title only | 56 px section icon tile + breadcrumb chevrons + 32 px bold title | Wayfinding: where am I, where did I come from (apple §16) |
| Status badge 12 px, static dot | 13.6 px semibold; live statuses (`running`, `in_process`, `loading`) pulse softly; neutral and success text darkened to pass AA 4.5:1 | Live things read as live; badges are on every list |
| `AppShell` showed "Checking your login…" forever when the server was down | "Can't reach the mill server" with Try again; each tab titled "Screen · Everest" | Honest status; tabs are distinguishable |
| Placeholder said "owned by Razan" | "Coming soon. Everything else in the menu works today." | No internal team names on user screens |
| Reduced motion zeroed everything; infinite pulses flickered | Transforms off, opacity/colour fades kept at 120 ms, `animation-iteration-count: 1`; `prefers-reduced-transparency` makes chrome solid; `prefers-contrast` darkens borders | Reduced motion means gentler, not none (apple §14) |
| Login: dark side panel, 26 px role chips that only fill | Centred card, 56 px brand mark, 51 px fields, black pill "Sign in", role tiles with icon + what the role does | First screen anyone sees; picking a role is one obvious tap |
| Floor tile: colour strip over a rounded corner, unlabelled "2 h 05 m", no press state | Status in the badge, stopped machines tint the whole card (red/amber ring), "Running for 2 h", status-coloured progress, `lift` press/hover, 40 ms stagger on load | Find the broken loom from across the floor; the most-tapped element responds |

## 2. Open findings by screen

Severity: high = blocks or misleads a user, med = slows or confuses, low = polish. File paths under
`frontend/src/`. Owners per `CODEOWNERS`; fixes in another owner's folder go through them.

### Floor, crew, insights, masters (Muaz)

| File:line | Before | After | Why | Sev |
| --- | --- | --- | --- | --- |
| production/api.ts:112, FloorForms.tsx:88,113 | Output/roll forms just clear the field on success | `notify("Logged 12.5 m on LM-03")` or inline `role="status"` | No proof it saved; staff log twice | high |
| lib/useSSE.ts:16, FloorBoard.tsx:34 | Says "updates live" even when the stream drops | `useSSE` returns live / reconnecting; header shows green "Live · 10:42" or amber "Reconnecting…" | Board goes stale silently on tablet Wi-Fi | high |
| FloorBoard.tsx:52, WorkOrderQueues.tsx:211 | Any refetch error replaces the whole grid | Error page only when there is no data; else a "showing 10:31 data · Retry" banner | One network blip wipes the board | high |
| MachinePanel.tsx:94 | `<StatusForm key={tile.status}>` | Key on machine id; keep typed reason when status changes underneath | SSE update while typing a breakdown reason loses the text | high |
| FloorForms.tsx:95,120 | Button disabled on bad qty with no reason | Keep enabled, show the inline message | Greyed button with no explanation | high |
| WorkOrderQueues.tsx:163, CrewBoard.tsx:194 | Finish job / end crew fire on one tap | Finish: confirm "340 of 400 m done". End crew: 5 s Undo | Irreversible one-tap actions next to Move/Resume | high |
| MachinePanel.tsx:51-110 | Today's history above the actions | Actions first, history collapsed | Most-used actions sit below a growing list | high |
| qc/page.tsx | QC home is a placeholder | Attention list + "Roll inspection coming soon" until built | A whole role lands on a dead end | high |
| FloorForms.tsx:57 | Status buttons filtered, so positions shift | All 5 in fixed order, current one disabled "Now" | Same thing, same place (apple §16 familiarity) | med |
| FloorBoard.tsx:77 | Tiles in server order | Breakdown → maintenance → idle → running → off | A broken loom can sit below the fold | med |
| MachineTile.tsx | Tile changes silently over SSE | 2 s ring on the tile that just changed | Show what changed, not only that something did | med |
| floor/page.tsx:8 | Attention list under all tiles | Beside the grid at `xl`, "Needs attention (3)" link below | To-do list is off-screen on tablets | med |
| MachinePanel.tsx:99 | Log output and Cut roll stacked, unexplained | Hint: "Log output = metres woven · Cut roll = take a roll off the loom" | First-time users can't tell them apart | med |
| WorkOrderQueues.tsx:132-198 | One pending state for all rows; reorder waits for the server | Per-row "Starting…", optimistic reorder, error in the row | No sign which button is working | med |
| WorkOrderQueues.tsx:175-190 | ↑ ↓ ⟲ Move Start in a wrapping row, Start last | Start first, the rest in a secondary row | Primary action ends up last at 375 px | med |
| CrewBoard.tsx:55,212,216 | Reason typed even for "Present"; rows don't look tappable; raw "crew"/"manual" | Quick-pick chips, chevron on rows, "From crew" / "Marked by hand" | Typing on a tablet for the routine case | med |
| analytics/InsightSheet.tsx:97,127,147 | 24 px record chips, `h-11 sm:h-9`, silent resolve | `min-h-11`, `pointer-coarse` sizes, notify + close on resolve | Too small at tablet width; no feedback | med |
| analytics/Delivery.tsx:33,122 | "Slack", "+3 d"; expand chevron in last column | "Spare time", "3 days spare"; whole row toggles | Planning jargon; control off-screen at 375 | med |
| analytics/InsightsPage.tsx:81 | "Run detectors now" | "Check for new findings" | Internal word | med |
| masters/useMasterForm.ts:15,35, MasterForm.tsx:97 | Dialog just closes; focus not moved to first error; derived-field errors dropped | Notify "Supplier KSM saved", focus `:invalid`, show unmatched errors | No proof; error can be off-screen | med |
| masters/FabricTypeForm.tsx:97 | Recipe inputs labelled only by placeholder | Header row Fibre · Count · Share %; stack at narrow widths | Meaning lost once typed | med |
| analytics/InsightSheet.tsx:93, masters/config.tsx:136 | "Yarn batche"; shift code rejects lower case | Singular label map; upper-case on input | Polish | low |

### Store, orders, dispatch, finance, tracking (Ammaar, Ashil)

| File:line | Before | After | Why | Sev |
| --- | --- | --- | --- | --- |
| inventory/ReceiveScreen.tsx:185 | Scan field `disabled={busy}`, focus not returned | Stay enabled, refocus in `onSettled` (as DispatchLoad does) | Next scanner read types into nothing | high |
| inventory/IssuePanel.tsx:78 | Ungated hover looks like "selected" on touch | Selected = ring + check icon; hover gated | Two lots look picked; wrong lot issued | high |
| dispatch/DispatchLoad.tsx:278 | Truck can be confirmed with no vehicle number | Require `vehicle_no`, hint "Add the vehicle number first" | Blank vehicle on an invoice that can't be edited | high |
| inventory/BatchSheet.tsx:130, finance/PaymentForm.tsx:22 | Approve / reject / payment succeed silently | "YB-000123 approved, 412 kg now free" / "₹25,000 recorded, ₹X outstanding" | Money and stock entered twice | high |
| inventory/ReceiveScreen.tsx:153, BatchSheet.tsx:251 | `size="sm"` buttons on store tablets | Default size (now 47 px; `sm` also grows on touch in this preview) | Touch target | high (fixed by shared `pointer-coarse`) |
| inventory/ui.tsx:14, dispatch/DispatchList.tsx:25, finance/types.ts:95 | Three more select style copies, `h-9`, no focus/invalid state | One shared Select (base rule in this preview sets min height and look) | Misaligned rows, no focus ring | high (partly fixed) |
| orders/OrderList.tsx:101 | Confirm closes the sheet silently | "Confirmed, yarn reserved" status or toast | User infers success from a badge | med |
| inventory/ReceiveScreen.tsx:125, IssuePanel.tsx:185 | Field errors go to a banner, or nothing happens | Error under the field via FormField | Error far from cause | med |
| inventory/IssuePanel.tsx:65,83 | "Check the to-buy list" (store can't open it); "FIFO next" | "Ask sales to buy it"; "Use first (oldest)" | Dead-end instruction; jargon | med |
| ReceiveScreen.tsx:177, OrderList.tsx:52 | `role="tab"` buttons with no tabpanel; view not in URL | Segmented radiogroup; `?view=to-buy` | Broken ARIA; can't link the to-buy list | med |
| inventory/StoreHome.tsx:54 | Every queue tile opens all batches | `/store/batches?status=…` | "In quarantine" shows everything | med |
| inventory/BatchSheet.tsx:161, ReceiveScreen.tsx:237 | Reject looks like approve; Confirm receipt has no confirm | Destructive variant; confirm dialog with totals | Irreversible actions look routine | med |
| ReceiveScreen.tsx:158, DispatchLoad.tsx:64 | Two-column only at `lg` | `md`, or sticky bottom bar with the main action | Confirm is below every list on 768 px tablets | med |
| inventory/StockScreen.tsx:42-101, orders/NewOrderForm.tsx:119 | Formulas as page subtitles; 10 columns scroll with no sticky first column | One plain sentence + "How this works" disclosure; sticky Yarn column | Rules where users expect instructions | med |
| tracking/OrderDetail.tsx:134,138, finance/Wages.tsx:161 | `navigator.clipboard` with no fallback; `window.confirm` | Fallback + "Copied" that resets; shared ConfirmDialog with a specific verb | Throws on plain-HTTP LAN; native unstyled dialog | med |
| dispatch/DispatchLoad.tsx:126 | Scan success and error look alike | Errors `role="alert"`, full-width red block, `navigator.vibrate?.(200)` | Noisy floor; multimodal feedback (apple §13) | med |
| StoreHome.tsx:66, finance/Month.tsx:135 | Links styled `text-primary` (now black, same as text) | `Button variant="link"` (blue `info`) | Links look like plain text after the colour change | med |
| tracking/StageCard.tsx:81, app/track/[token]/page.tsx:29 | Current step only by colour; raw API error as title | `aria-current="step"`; "This tracking link no longer works" | Buyer-facing page | med |
| assorted | "1 lots", "1 rolls"; amber vs red for "short"; `undefined (undefined)` | Plural helper; red everywhere for short; guard missing receipt | Polish | low |

## 3. Cross-cutting work left (do once in `components/`)

1. **Feedback channel.** Add one `notify()` with Undo slot and call it from every mutation's `onSuccess`.
   Sonner is the standard choice, but it is a new dependency and needs team OK (CLAUDE.md). The
   alternative is about 30 lines with a `role="status"` region in AppShell.
2. **ConfirmDialog** with a specific verb button, replacing `window.confirm` and guarding irreversible
   actions (finish job, confirm receipt, reject, lock wages).
3. **Select and Textarea** components, so screens stop copying `selectClass`.
4. **FormField wires accessibility itself** (ids, `aria-describedby`, `aria-invalid`) and exports one `FormError`.
5. **QueryView** that keeps cached data on refetch errors and shows a stale banner; an SSE status context.
6. **One Stat tile and the Table primitive** for the four stat-tile variants and ten raw tables.
7. **Status vocabulary**: explicit label map in StatusBadge, delete RiskBadge/LevelBadge copies.

## 4. How it was checked

- `tsc --noEmit` clean. Screens captured with headless Edge at 1280 px in light and dark from the live
  app with a simulated month of data. Target is desktop only.
- The two per-screen tables were produced by reading every file against both skills; line numbers are from
  `main` at `cf077bf`.
