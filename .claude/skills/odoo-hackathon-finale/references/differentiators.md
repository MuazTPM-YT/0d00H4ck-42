# Differentiators (Textile PS): what to build beyond the six scenes

Read this after `textile_manufacturing.md`. The base checklist comes first; nothing here starts until every Core item works end to end.

## Positioning (use in README, video and pitch)

"Odoo covers breadth. We built textile depth and intelligence that runs on the mill's own server: no cloud, no credits, works when the internet doesn't."

Why this holds up (research, Oct 2026):
- Odoo 20 (released 24 Sep 2026) is AI-first: Ask AI, AI agents, AI fields, an MCP server. A generic "chat with your ERP" feature copies what Odoo just shipped. Do not build one.
- Odoo 20 AI runs only through Odoo's cloud service, billed in credits, with no own-key option, and agents need a public webhook, so private self-hosted databases cannot use agents. Mills often self-host on a factory LAN.
- Native Odoo has generic lot tracking; textile specifics (dye lot, shade band, GSM, width, shade continuity, yield) are sold as partner customizations.
- Shade variation is widely cited as the most frequent reason buyers reject fabric rolls.

Tone with Odoo judges: complementary, never dismissive. "This could ship as an Odoo module" is the frame.

## D1. Lot continuity, yarn to dispatch (build first)

One story across the chain: reserve one yarn lot per order where possible (prevents barre), carry the yarn lot onto every roll, assign shade band at QC, dispatch one shade band per order. The dispatch half is below.

### Shade-safe dispatch

- At QC, each passed roll gets `dye_lot` and `shade_band` (A, B, C) besides pass/rework/reject. Also store `gsm` and `width_cm`.
- Dispatch builder for an order auto-selects rolls from a single shade band to fill the quantity (largest band that covers it; otherwise fewest bands, flagged).
- Server rejects mixing shade bands in one dispatch unless a supervisor overrides with a reason (logged).
- Demo: try adding a band-B roll to a band-A dispatch, get blocked with a clear message.

## D2. Delivery risk early warning

- Projected finish per order = remaining metres / recent throughput of its assigned machines (last N shifts), plus queued QC time.
- Status: On track / At risk / Late, compared with deadline. Dashboard list sorted by risk. Buyer tracking page shows the projected date.
- Deterministic and explainable. Call it a forecast, not AI. Show the formula on hover.

## D3. Roll genealogy and root cause

- Roll → order, machine, shift, operator, and the yarn GRN lot it consumed.
- Defect rate by machine, by shift, by yarn supplier. Click a failed roll to see its full chain.
- Note: Odoo 20 added a per-vendor quality rate, so judges will recognise the idea. The extra step here is linking defects to machine and shift as well as supplier.

## D4. True cost per order (Core scene, make it excellent)

- Yarn cost from actual GRN unit costs consumed (FIFO), labour by machine-hours per shift, machine running cost per hour, plus cost of rework and rejected rolls attributed to the order.
- Show planned vs actual and margin per order.

## Cheap Indian-context realism (only if time)

GSTIN and HSN code on invoices, rupee formatting, kg for yarn and metres for fabric everywhere.

## AI layer (agreed)

Local, explainable, grounded: facts from the ledger, statistical detectors (supplier tracing via lineage, defect root cause by lift, MAD-based machine anomalies, yarn yield leakage, impossible data), and a local LLM via Ollama that only phrases computed facts with record links and falls back to templates when the model is off. Validated against planted problems in a simulated month (precision and recall). Full spec: Prompt 05 / `docs/ai.md` in the repo.

## Do not build

Generic CRM, HRMS beyond attendance and wages, a chatbot, blockchain, job work/subcontracting, e-way bill integration.
