---
name: odoo-hackathon-finale
description: Judging criteria, build rules and delivery protocol for Team 42 at the Odoo x NMIT Bangalore Hackathon 2026 Grand Finale. Use this skill for EVERY request in this hackathon build, including planning, schema design, writing or reviewing code, UI work, git commits, README, demo video script and final presentation, even when the user does not mention Odoo, judging or the hackathon. Also use it whenever the user mentions the Textile Manufacturing System or Student Organization System problem statements, the evaluator, submission, or asks "is this good enough to win".
---

# Odoo x NMIT Hackathon 2026: build to win

The goal is first place. The evaluator scores what they can see and verify: the running app, the repo, the commit history, the video and the team's ability to explain the code. Every decision in this build should make one of those things better. When a choice is between "impressive but fragile" and "simple, complete and explainable", pick the second. Odoo is an ERP (Enterprise Resource Planning) company; its evaluators read code and schemas for a living and will spot shortcuts.

## 1. Event facts (do not lose these)

- Team Number 42. Leader: Mohammed Ashil. Members: Ammaar, Muaz Ismail Mohammed, Muhammed Razan.
- Problem statements on offer: `Textile_Manufacturing_System` and `Student_Organization_System`. The team leader selects one. If the chosen PS (problem statement) text is not in context, ask for it before designing anything.
- Evaluator: Bhavya Mehta, GitHub `mebh-odoo` and `hackathon-odoo`. Both accounts must be added as collaborators on the repo by **10 Oct, 11:00 AM**. If this is not confirmed done, say so at the top of the reply.
- Coding ends **11 Oct, 10:00 AM**. Video links due **11 Oct, 10:30 AM**. Presentations and valedictory **11 Oct, 1:00 PM**.
- Prize stakes: ₹45,000 for the winner, plus possible fresher offers at 5 to 8 LPA (lakh per annum) for exceptional performers. Individual explainability matters for the offers, not only the team score.

## 2. Source criteria (verbatim from the event page)

Must have:
1. Use real-time or dynamic data sources, and avoid relying on static JSON unless it's for initial prototyping.
2. Create a responsive and clean UI (Consistent color scheme and layout).
3. Validate user input robustly.
4. Use intuitive navigation with proper menu placement and spacing.
5. Use version control (Git) properly; one member managing the repo is not enough.

Nice to have:
1. Ability to design backend APIs, model data, and set up a local database.
2. Understand AI/code snippets thoroughly before using them; don't blindly copy-paste without adapting them to your project.
3. Plan for offline or local solutions and don't rely entirely on internet connectivity or cloud-based tools.
4. Use trendy technologies only if they add real value to your project.

Also stated: "we value your skills, more than your resume."

Treat the nice-to-haves as must-haves. The finale field will have most teams meeting the must-haves; the nice-to-haves are where the ranking gets decided.

Assumption, not on the page: past Odoo hackathons have scored along lines like coding standards, logic, modularity, database design, frontend design, performance, scalability, security, usability and debugging. The rules below cover all of these anyway, so nothing breaks if the actual rubric differs.

## 3. How each criterion translates into build rules

### 3.1 Dynamic data, no static JSON

What the evaluator checks: does data come from a database through an API, and does the UI change when data changes?

- All app data lives in the local database and reaches the UI through backend API calls. No `import data from './data.json'` in the frontend, no hardcoded arrays rendering lists, no fake numbers on dashboards.
- Demo data is created by a seed script that writes into the database (`npm run seed`, `python manage.py seed`, etc.), never by JSON files the UI reads directly. The seed script itself is fine to commit and mention.
- Every create, update and delete is reflected immediately everywhere it appears (lists, counts, dashboards) without a manual page reload.
- Add at least one genuinely live element where the PS makes it meaningful: a dashboard or status board that updates via polling, SSE (Server-Sent Events) or WebSockets when another user changes data. Two browser windows side by side updating each other is a strong demo moment.
- Dashboard KPIs (Key Performance Indicators) and charts are computed from real rows with real queries, not precomputed constants.

### 3.2 Responsive, clean, consistent UI

What the evaluator checks: does it look like one product, and does it hold up when the window shrinks?

- Define design tokens once (colors, spacing scale, radius, font sizes) as CSS variables or a theme config, and use only those. No one-off hex codes or random pixel values in components.
- One primary color, one neutral scale, plus semantic colors for success, warning, danger, info. Status badges use the same color for the same meaning everywhere.
- Check every screen at roughly 375px (phone), 768px (tablet) and 1280px (laptop). Tables become scrollable or card lists on small screens; nothing overflows the page horizontally.
- Every data view has loading, empty and error states. An empty table with no message reads as broken.
- Consistent page skeleton: same header, same page title position, same primary action placement (top right of the page), same form layout.
- Optional edge, worth it if cheap: borrow Odoo's own UX patterns the judges live in daily, such as list view plus form view, a kanban view for workflow stages, a status bar showing record state (Draft → Confirmed → Done), and an activity log on records. Do not copy Odoo branding.

### 3.3 Input validation

What the evaluator checks: they will type garbage into forms. Assume it.

Validate at three layers and say which layer catches what:
- **Client** for instant feedback: required fields, formats, ranges, inline field-level messages next to the field, submit disabled while invalid or in flight.
- **Server** as the authority: validate every request body with a schema library (Zod, Pydantic, Joi or equivalent). Never trust the client. Return a consistent error shape, for example `{ "error": { "field": "quantity", "message": "Must be greater than 0" } }`, with correct HTTP status codes (400, 401, 403, 404, 409, 422).
- **Database** as the last guard: NOT NULL, UNIQUE, CHECK constraints, foreign keys, sensible types (numeric for money and quantities, not text).

Cover the cases teams forget: whitespace-only strings, negative or zero quantities, end date before start date, duplicate unique values (emails, codes, roll numbers), stock or capacity going negative, overlong input, invalid email or phone, file type and size on uploads, and business rules from the PS (a state transition that should not be allowed must be rejected by the server, not just hidden in the UI).

Show validation in the demo video on purpose. It is cheap to show and easy for judges to tick.

### 3.4 Navigation and layout

- A persistent sidebar or top navigation with modules grouped the way a user thinks about the domain, not the way the database is structured.
- Active menu item highlighted. Breadcrumbs on detail pages. Back navigation never loses context.
- Role-based menus if the PS has roles: each role sees only what it can use.
- Key flows reachable in three clicks or fewer from the dashboard. Count them for the main PS flows.
- Spacing from the spacing scale only. Menus and action buttons must not crowd each other.

### 3.5 Git, used by all four members

What the evaluator checks: the commit graph. One person pushing everything is called out on the page as not enough.

- Every member commits from their own GitHub account, on their own machine. If Claude writes code for a member, that member reviews it, understands it, and commits it themselves.
- Branch per feature (`feat/production-orders`, `fix/stock-validation`), merged via PRs (Pull Requests) with a one-line description. Protect `main` from direct pushes if time allows.
- Small, frequent commits with meaningful messages in Conventional Commits style: `feat(inventory): block issue when stock is insufficient`, `fix(auth): hash passwords with bcrypt`. No "update", "final", "final2", "changes".
- Commit early and steadily through the 24 hours. A burst of 40 commits at 9:55 AM looks like a dump.
- `.gitignore` covers `node_modules`, `venv`, `.env`, build output, local DB files. No secrets in the repo; ship a `.env.example`.
- When Claude finishes a chunk of work, end with a suggested commit message and which member should own that commit, so ownership stays spread across the team.

## 4. Nice-to-haves, made concrete

### 4.1 Backend APIs, data model, local database

- Use a local relational database: PostgreSQL by default (Odoo itself runs on PostgreSQL, which judges will notice), SQLite if setup time is the bottleneck. Run it on the laptop or in a local Docker container.
- Do not use BaaS (Backend-as-a-Service) such as Firebase or hosted Supabase as the core backend. It removes the exact skills the "design backend APIs, model data, local database" line is testing, and it breaks the offline line too.
- Design the schema before writing UI. Normalize to a sensible level, name tables and columns consistently, use foreign keys, add indexes on columns that are filtered or joined, and use migrations (Prisma, Drizzle, Alembic, Django migrations, etc.) rather than hand-edited tables.
- Put an ER (Entity-Relationship) diagram in the README. Mermaid is fine.
- Keep a clear API layer: resource-oriented routes (`GET /api/production-orders`, `POST /api/production-orders/:id/confirm`), consistent JSON shapes, pagination on list endpoints, filtering and search where the PS implies it.
- Auth: hashed passwords (bcrypt or argon2), sessions or JWT (JSON Web Tokens) with expiry, role checks enforced on the server per endpoint.
- Structure the code in layers (routes → services/business logic → data access) so modularity is visible from the folder tree.

### 4.2 Understand every line (AI-written code included)

This is the biggest risk for this team, because Claude is writing a lot of the code. Expect the evaluator to point at a file and ask a specific member "why did you do it this way?"

Rules for Claude:
- Prefer plain, readable code over clever code. No obscure library unless it saves real time and the team can explain it.
- After writing any non-trivial piece (schema, auth, a business rule, a real-time mechanism), add a short "How this works" note in the reply: what it does, why this approach, what the alternative was. Three to six sentences.
- Add brief comments only where the "why" is not obvious from the code. No comment noise.
- Adapt to the project: no leftover boilerplate, placeholder names, unused imports, commented-out blocks, `console.log` debugging or tutorial-style names like `foo` or `myComponent`.
- Maintain a `docs/explainer.md` listing each module, who owns it, and the two or three questions a judge is most likely to ask about it with short answers. Update it as modules land.

### 4.3 Offline and local first

- The app must run fully on `localhost` with no internet: local DB, local file storage for uploads, fonts and icons bundled rather than pulled from CDNs (Content Delivery Networks) at runtime.
- If any feature needs the internet (an external API, an AI model), it must degrade gracefully with a clear message, and the rest of the app keeps working. Mention this behaviour in the demo.
- One-command setup in the README (`docker compose up`, or install, migrate, seed, run). Test it from a fresh clone before the deadline.

### 4.4 Trendy tech only with a reason

- No blockchain, no bolted-on chatbot, no "AI" label on a feature that is really a filter.
- An AI feature is allowed only if it removes a real pain point in the chosen PS (for example, forecasting material shortfall in textile production from actual order data), runs or degrades locally, and every member can explain it. Otherwise skip it and spend the time on completeness.
- If the team asks for something trendy, state the value it adds and the time it costs before building it.

## 5. Problem statement handling

Once the PS is chosen and pasted:
1. Extract every explicit requirement into a numbered checklist in `docs/requirements.md`. Mark each as Core, Expected or Stretch.
2. Map each requirement to a screen, an API endpoint and a table. Anything unmapped is a gap and must be called out.
3. Build all Core items end to end (UI, API, DB, validation) before starting any Stretch item. A complete thin app beats a wide half-working one.
4. Re-check the checklist at every major milestone and report status in one compact table.

ERP-style features judges at Odoo expect for either PS, where the PS supports them: role-based access, record lifecycle states with allowed transitions, search and filters on lists, a dashboard with real aggregates, an audit or activity trail on key records, and at least one report or export (CSV or PDF).

## 6. Time plan (24 hours, 10 Oct 10:00 AM to 11 Oct 10:00 AM)

- **10:00 to 11:00 Oct 10:** PS chosen, requirements checklist, schema and API outline, repo created, all four members and both evaluator accounts added, skeleton committed by everyone.
- **11:00 to 22:00:** Core features end to end, split by module across members. Design tokens and layout shell set up in the first two hours so every screen inherits them.
- **22:00 to 04:00 Oct 11:** Expected features, validation pass across all forms, responsive pass, real-time element, seed data that looks realistic.
- **04:00 to 07:00:** Feature freeze at 07:00. Bug fixing only. Fresh-clone setup test. README, ER diagram, explainer doc.
- **07:00 to 08:30:** Record a full backup demo video. Do not leave the only recording for after 10:00, because the window between coding end and video deadline is 30 minutes.
- **08:30 to 10:00:** Final fixes, re-record if the app improved, last commits from every member.
- **After 10:00:** Upload video, submit link by 10:30. Rehearse the presentation before 1:00 PM.

If the team is behind schedule, Claude should say so plainly and propose what to cut, cutting Stretch items first and never cutting validation or git hygiene.

## 7. Demo video and presentation

Structure (aim for whatever length the organisers specify; if none, 3 to 5 minutes):
1. The problem in one sentence, from the user's side.
2. The main flow end to end, as a real user, with realistic data.
3. Validation catching bad input on one or two forms.
4. Live update across two windows or roles.
5. Responsive view on a narrow window.
6. Ten seconds on architecture: local DB, API layer, schema diagram, offline behaviour.
7. Each member speaks for their own module if the format allows it.

For the 1:00 PM presentation, every member should be able to answer: what does your module do, why this schema, how is input validated, what happens offline, what would you build next.

## 8. Definition of done for any feature

Before Claude calls a feature finished, it must satisfy all of these. If one is skipped, say which and why.
- Data comes from the DB via an API; no hardcoded or JSON-file data in the UI.
- Client, server and DB validation in place, with field-level error messages.
- Loading, empty and error states present.
- Uses design tokens only; checked at phone, tablet and laptop widths.
- Reachable from navigation; active state and breadcrumbs correct.
- Server enforces permissions for the endpoint.
- No dead code, debug logs or unused imports.
- "How this works" note given, and `docs/explainer.md` updated if it is a new module.
- Suggested commit message plus suggested owning member.

## 9. Behaviour rules for Claude during this build

- Before writing code for a request, check it against sections 3 and 4. If the request would break a criterion (for example "just hardcode the dashboard numbers" or "use Firebase, it's faster"), say which criterion it breaks, give the compliant alternative and its time cost, and let the team decide.
- Prefer the stack the team already knows. Speed and explainability beat novelty.
- Keep files small and modules separated so ownership can be split across four people without merge conflicts. Flag likely conflicts when two members touch the same file.
- When reviewing code the team wrote, score it against section 8 and list concrete fixes in priority order.
- Push back when something looks done but would fail a judge's poke: a form that accepts negative quantities, a list that does not refresh, a button that only works for the admin.
- Point out deadline risks from section 1 whenever the current time makes them relevant.

## 10. Final submission checklist (run before 10:00 AM, 11 Oct)

- [ ] Evaluator accounts `mebh-odoo` and `hackathon-odoo` have repo access.
- [ ] All four members have meaningful commits spread across the 24 hours.
- [ ] `main` builds and runs from a fresh clone using the README steps.
- [ ] Seed script produces realistic demo data; no JSON data files read by the UI.
- [ ] Every PS Core requirement is marked done in `docs/requirements.md`.
- [ ] Every form rejects bad input at client and server.
- [ ] All screens checked at phone, tablet and laptop widths.
- [ ] App runs with Wi-Fi off.
- [ ] README has setup, features, tech stack with reasons, ER diagram, screenshots, team roles.
- [ ] `.env.example` present, no secrets committed.
- [ ] Demo video recorded, uploaded, link tested in an incognito window.
- [ ] Each member has rehearsed answers for their module.
