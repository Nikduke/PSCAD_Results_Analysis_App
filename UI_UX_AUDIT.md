# PSCAD Results Analysis — UI/UX Audit

Date: 2026-09-26

Status: audit with one follow-up visual correction. The broader audit recommendations remain unimplemented.

## Executive judgement

The application has a strong foundation for an experienced PSCAD analyst: the
main workflow is visible in one window, project-specific state is surfaced in
the project header, the preview table and run log provide useful observability,
and the light/dark styling is coherent. The largest usability risks are not
cosmetic. They are the lack of first-run guidance, the ambiguous distinction
between the active project and checked projects, the unlabeled RMS enable
control, the dense/duplicated action surface, and the absence of determinate
progress for long analysis runs.

The highest-value update would be a small information-architecture pass around
the existing widgets rather than a redesign: make the empty state actionable,
make selection scope explicit, give RMS a real label, group the stage actions,
and expose progress at the same project/scope/stage granularity already used by
the analysis pipeline.

## Scope and evidence

### Repository and workflow understanding

The workflow was derived from the current repository documentation and source:

- README.md, docs/HANDOFF.md, docs/CURRENT_CONTEXT.md, and
  docs/ANALYSIS_METHODS.md;
- the graphify code map for the UI/orchestration relationships;
- the PSCAD documentation context for result-project, case/run, waveform,
  output, and project terminology;
- main_window.py, settings_dialog.py, styles.py, models.py, and scanner.py;
- focused UI/theme tests in tests/test_ui_models.py.

The five operating regimes reviewed were project/session, scan/catalog,
envelope/check, batch/render/report, and rebuild-only.

### Follow-up visual correction

The light-theme Settings screenshot exposed a rendering defect in the small
increase/decrease controls of `QSpinBox` and `QDoubleSpinBox`: the custom
stylesheet border caused Qt to render separator-like horizontal marks instead
of the native up/down arrow glyphs. The stylesheet now keeps themed field
colours, padding, selection, and disabled colours while leaving the native
spin-box frame and arrow controls available to Qt. The regression test
`test_spinbox_arrows_remain_visible_in_light_and_dark_themes` covers enabled
and disabled states in both themes. The full suite passed with 298 tests and
3 skips after this correction.

### Application and harness evidence

The packaged executable was launched from:

dist/PSCADResultsAnalysis.exe

The native-window Computer Use connector was not exposed in this session: its
inventory returned no native applications and only browser controls, although
the executable process was open and responsive. Therefore, no claim is made
about native Windows font rendering, actual DPI scaling, or native file-dialog
interaction.

Following the task instructions for unavailable direct UI interaction, an
audit-only Qt harness instantiated the same MainWindow, settings dialog, and
theme classes without changing production code. It rendered temporary evidence
under .tmp/ui_ux_audit/:

- main_window_light.png
- main_window_dark.png
- main_window_real_scan.png
- settings_build_light.png
- settings_resonance_light.png
- settings_sustained_dark.png

The offscreen environment did not provide the production font, so the rendered
images are useful for geometry, grouping, colour, and state inspection but not
for judging glyph shape or final Windows typography.

The real sample project ../Original_examples/03_Test_project_case was scanned
read-only. The scan exposed 3 cases, 3 voltages (66/161/230 kV), 78 aggregated
High Voltage rows, and the existing Ready/No dashboards/Plots exist/Reports
exist status combination. The resulting project row and preview row were
rendered in the harness.

Additional audit-only checks:

- Requested window widths of 1440, 1280, 1024, and 800 px were applied to the
  main window.
- Settings dialog tab structure and minimum sizes were inspected.
- The no-project Run analysis path was invoked.
- Busy-state enablement and progress-bar state were inspected.
- A nonnumeric chart-limit cell was entered through the settings harness.
- Two-project dashboard figure sharing was inspected.
- Splitter sizes were changed, the window was recreated, and the reset behaviour
  was observed.
- pytest -q tests/test_ui_models.py: 38 passed.

Findings below distinguish confirmed UX problems from presentation
improvements and subjective alternatives.

## Findings

### F-01 — Empty startup state does not teach the first action

Severity: High
Type: Confirmed UX and discoverability problem

**Current behaviour.** On a new session the window opens with the full control
surface, an empty project tree, a checked Full scope, blank preview/dashboard
lists, and a Ready status. The primary analysis and report actions remain
visible and enabled. Pressing Run analysis with no project does not show an
inline explanation or a project picker; it only appends
Run analysis skipped: select at least one project and one scope. to the log.

**Problem.** A first-time user is asked to infer the order of operations from a
blank dashboard. The useful recovery instruction is hidden in a secondary log
panel, while the prominent action looks available. The same pattern applies to
dashboard actions when there are no checked projects.

**Evidence.** The empty-state render had zero project rows, status Ready, and
no preview rows. The harness invocation of run_full_analysis() left the status
as Ready and changed only the log text. The relevant UI construction is in
main_window.py:622-686, main_window.py:957-1010, and the guard is
main_window.py:2810-2815.

**Proposed improvement.** Add a clear empty-state message in the project/preview
workspace: “Add a PSCAD results project to begin,” with Add project as the
primary action and a short three-step hint. Disable or visually de-emphasize
actions that require selected work until a project and scope are checked, with
state-specific tooltips. Keep global settings available.

**Expected benefit.** The first successful path becomes obvious without
requiring the README, and a mistaken click has an immediate explanation.

**Guardrail.** Do not remove the existing log message; it remains useful for
automation and for experienced users. Keep the Full scope default.

### F-02 — RMS has an unlabeled enable checkbox

Severity: High
Type: Confirmed discoverability and accessibility problem

**Current behaviour.** The top analysis row contains a checkbox with no visible
text followed by an RMS button. The checkbox enables RMS; the button opens the
project-specific quantity/MM-element selector. The checkbox is discoverable
only through its tooltip.

**Problem.** The two controls look like one small, unexplained control cluster.
Users must hover or experiment to learn whether the checkbox enables RMS, opens
RMS settings, or represents an unlabeled status. The empty checkbox also has a
poor accessible name.

**Evidence.** main_window.py:515-522 constructs QCheckBox with no label. The
audit harness enumerated the visible checkbox labels and found no RMS label,
while the adjacent button was simply RMS.

**Proposed improvement.** Use a visible RMS checkbox label and rename the
adjacent button to Configure RMS, or use a compact labelled group such as
[ ] RMS  Configure.... Preserve the existing disabled state when no checked
project has MM elements.

**Expected benefit.** The control becomes self-explanatory, keyboard/screen
reader navigation gains a meaningful name, and the distinction between enable
and configure is retained.

**Guardrail.** Keep the current one-click selector and project-specific
semantics; this is a labelling change, not a calculation or workflow change.

### F-03 — Active project and projects to analyse are different states but look similar

Severity: High
Type: Confirmed mental-model and consistency problem

**Current behaviour.** A project-tree checkbox controls whether a project is
included in batch work. Selecting a row controls the current/active project
whose settings, exclusions, RMS selector, dashboard header, and project
controls are shown. The active row is made bold, and the group title changes to
Project: <name>, but the screen does not explicitly explain the two states.

**Problem.** A user can check several projects and then change the active row
without realizing that settings/exclusions apply to only the highlighted
project while analysis actions apply to all checked projects. The visual
difference between a checked row and the active row is easy to miss.

**Evidence.** The separate behaviours are implemented in
main_window.py:1518-1572, main_window.py:1600-1618, and
main_window.py:2634-2667. The real-scan render showed one checked project
with the same row simultaneously acting as the active context; the distinction
only becomes visible with multiple rows.

**Proposed improvement.** Add a small legend or inline helper above the tree:
“Checked = included in analysis; highlighted = active project for settings.”
Label the group Active project: <name> and add a compact summary such as
2 checked / 4 projects. Make the active row indicator more explicit than bold
text alone.

**Expected benefit.** Multi-project users can predict which state a click will
change and are less likely to configure one project while analysing another.

**Guardrail.** Preserve the existing checkbox selection semantics and the
canonical project-specific state model. Do not turn row selection into another
analysis selection.

### F-04 — The main action surface is dense and repeats ambiguous stage labels

Severity: High
Type: Confirmed discoverability and terminology problem

**Current behaviour.** The top bar contains project controls, voltage/event/check
selection, dashboard scanning/updating, Run analysis, Rebuild reports, and
Stop. The Scopes panel separately contains Build envelope data/checks,
Rebuild heatmaps, and two columns each containing Rebuild charts, Create
batches, and Render plots. The two Rebuild charts and two Render plots buttons
have different targets but identical visible labels.

**Problem.** New users cannot easily tell which buttons are the normal path,
which are rebuild-only actions, and which are safe to run from existing
outputs. Experienced users must repeatedly read tooltips or remember the
pipeline. The top bar is also visually close to its width limit.

**Evidence.** The rendered main window shows the entire action row and the
stacked Analysis Steps group. The construction is in
main_window.py:477-619 and main_window.py:897-946; the distinguishing meaning
is available only in tooltips at main_window.py:929-936.

**Proposed improvement.** Keep the existing stage functions but reorganize their
presentation into a clear primary path and an Advanced/rebuild area. Rename
duplicate labels to include their object, for example Rebuild event charts,
Rebuild analysis charts, Render event plots, and Render analysis plots. Make
the normal path visually dominant and collapse or hide rebuild-only steps
behind an Advanced steps disclosure.

**Expected benefit.** The action hierarchy becomes teachable while power users
retain the same narrow operations and direct access.

**Guardrail.** Do not make Run analysis silently invoke dashboard refresh or
other currently separate operations. Preserve the current stage boundaries and
tooltips as secondary detail.

### F-05 — Long-running work has no determinate progress model

Severity: High
Type: Confirmed feedback problem

**Current behaviour.** Starting a background action disables most of the
workspace, shows Stop, changes the status text, and displays an indeterminate
progress bar. The log receives timestamped messages. The progress range is
explicitly 0, 0, so it cannot show completed projects, scopes, voltages, or
stage progress.

**Problem.** Envelope reads, plotting, Excel exports, and reports can take long
enough that users cannot estimate whether the run is advancing, which project
is active, or how much work remains. A log is useful for diagnosis but is a
poor primary progress indicator.

**Evidence.** The busy harness state showed status Running analysis, an
indeterminate visible progress bar, and Stop enabled. The implementation is
in main_window.py:3898-3934 and main_window.py:4054-4110.

**Proposed improvement.** Keep the current busy lock and Stop action, but add
stage/project/scope progress where counts are known, for example:
Envelope build — project 2/5 — scope Full — voltage 161/230 kV.
Use determinate progress for known loops, an indeterminate state only for
single opaque Excel/file operations, and a completion summary with outputs,
skips, warnings, and failures.

**Expected benefit.** Users can trust that a large run is progressing and can
make a better decision about waiting or stopping.

**Guardrail.** Progress must reflect completed work, not an invented time
estimate. Keep the log as the detailed audit trail and preserve safe
cancellation at operation boundaries.

### F-06 — The main window is not responsive below a wide desktop layout

Severity: High
Type: Confirmed visual/layout problem

**Current behaviour.** The window imposes a minimum width of approximately
1772 px and a minimum height of approximately 640 px in the Qt harness. The
top bar alone has a minimum width of approximately 1760 px. A requested width
of 1440, 1280, 1024, or 800 px was clamped to 1772 px rather than adapting.
The Settings dialog requested 1120×760 but its measured minimum size was about
1308×691 because of tab contents.

**Problem.** Users on a 1366 px laptop, a split-screen desktop, or a display
with high scaling may get a window larger than the usable work area. Even when
Windows maximization compensates, the interface cannot be meaningfully
rearranged for a smaller viewport.

**Evidence.** The size checks returned main-window minimum 1772×640 and Settings
minimum 1308×691. The source sets fixed panel minimums and initial splitter
sizes in main_window.py:416-435, main_window.py:622-624, and
main_window.py:862-865.

**Proposed improvement.** Add a narrow-layout mode: allow the top controls to
wrap or move into a compact Selections panel, make the project/scope and
preview panels collapsible, and use a tab/stacked arrangement below a
documented breakpoint. Make Settings scroll vertically rather than forcing a
large horizontal minimum.

**Expected benefit.** The same workflow becomes usable on practical laptop and
scaled-display sizes while preserving the current dense wide-desktop layout.

**Guardrail.** Do not remove the splitters for large monitors. Retain user
resizing and test at Windows 100%, 125%, and 150% scaling before rollout.

### F-07 — Settings mixes basic, expert, global, and project-specific decisions

Severity: Medium
Type: Confirmed information-architecture problem

**Current behaviour.** The Settings dialog has six tabs: Envelope Build,
Envelope Chart, Voltage Um, Events, Sustained SDPF, and Resonance Checks.
The Resonance Checks page includes a short user-facing form followed by a
large Algorithm constants group. The Envelope Build tab mixes worker policy,
project scans, incremental cache, waveform exports, timing, frequency, and
engineering limits. Some values are app-wide, some apply to the selected
project, and the selected project name is not a persistent title in every
tab.

**Problem.** Users must know which values affect all projects, the active
project, or only the next operation. The project-specific Cache analyzed run
data checkbox is disabled with no project but its scope is mainly conveyed by
the tooltip. Advanced constants occupy the same navigation level as routine
settings.

**Evidence.** The harness found six tabs and a Settings minimum size of about
1308×691. The settings construction and project-specific cache enablement are
in settings_dialog.py:31-110 and settings_dialog.py:184-889.

**Proposed improvement.** Add an explicit context line at the top:
Applying to active project: <name> or Application-wide setting. Group routine
settings first and put algorithm constants behind an Advanced disclosure or
separate tab. Add short always-visible help for cache ownership, invalidation,
and storage rather than relying on hover.

**Expected benefit.** Users can safely change settings without guessing their
scope, and common settings require less scrolling.

**Guardrail.** Keep the existing tab names and persisted values during the
first iteration if possible; reorganize presentation before migrating any
settings schema.

### F-08 — Invalid table input can be silently ignored

Severity: High
Type: Confirmed engineering-trust and feedback problem

**Current behaviour.** Numeric spin boxes have bounds, but editable table cells
such as chart Y limits and Voltage Um values are plain text cells. In Settings,
the Y-limit parser returns None for a nonnumeric value and the Um loop skips
values that cannot be parsed. No inline error, warning, or failed-save state is
shown.

**Problem.** A user can type an invalid engineering value, click OK, and
believe the value was applied when the app has actually discarded it or
reverted to a different value. Silent fallback is especially risky for chart
limits and voltage configuration because it can change the interpretation of
reviewed outputs.

**Evidence.** settings_dialog.py:910-973 uses optional_number() and float()
parsing without a user-facing validation path. In the audit harness, entering
not-a-number into the first Y-min cell completed with status Ready, an empty
log, and the stored Y-min set to None.

**Proposed improvement.** Validate editable cells before accepting Settings:
highlight the cell, show the expected unit/range, and keep the dialog open
until the user corrects or explicitly clears it. For an intentionally blank
value, provide a clear reset action. Apply the same validation pattern to Um
and Sustained SDPF manual limit cells.

**Expected benefit.** Users can distinguish cleared/reset from invalid and
ignored, reducing silent changes to engineering output presentation and
configuration.

**Guardrail.** Do not change calculation defaults or silently clamp values.
Validation should expose the existing accepted ranges and preserve the current
meaning of a blank optional limit.

### F-09 — Exclusion tables use an ambiguous positive label for a negative action

Severity: Medium
Type: Confirmed consistency and terminology problem

**Current behaviour.** Manual, NonConv, and High Voltage tables use an Apply
column with checkboxes. The tooltip says checked rows are excluded from
envelope builds. For High Voltage, unchecking a detected row creates an
include override so the item is allowed through the next build. Proposal tabs
appear only when their scan has rows.

**Problem.** Apply does not tell users whether the row is excluded, included,
or merely selected for review. The meaning of an unchecked detected proposal is
the reverse of what many users will expect from an Apply checkbox. The
technical distinction is important but is primarily discoverable by hovering.

**Evidence.** The real sample scan rendered 78 High Voltage rows and exposed
Manual and High Voltage tabs. The tables are defined in
main_window.py:690-858; row semantics are defined by the tooltip in
main_window.py:1779-1786 and the High Voltage override logic in
main_window.py:2020-2058.

**Proposed improvement.** Rename the column to Exclude for rows that will be
removed from envelope builds. Add an always-visible note above proposal tables:
Checked = exclude; unchecked = include override. Show an explicit Included by
override state/source for an unchecked automatic proposal rather than relying
on the checkbox alone.

**Expected benefit.** The control communicates the engineering consequence at
the point of decision and reduces accidental inclusion/exclusion.

**Guardrail.** Preserve the existing normalized rule and exact
voltage/Case/Run/Bus override semantics. Only the presentation and explanation
should change.

### F-10 — Shared dashboard figure mode is easy to misread in multi-project work

Severity: Medium
Type: Confirmed mental-model problem

**Current behaviour.** The Dashboard Figures header names the active project,
but All checked is enabled by default and causes the list to show the union
of cached figures across checked projects. The same checked figure set is then
used for every checked project, with unavailable figures skipped per project.

**Problem.** A user may read Dashboard Figures: project_a and assume every
listed figure belongs to project_a, then unknowingly include a figure from
project_b in the shared selection. The tooltip explains the rule, but the
state is not visible at a glance.

**Evidence.** The two-project harness produced header Dashboard Figures:
project_a, All checked = true, and two list items, one from each project.
The implementation is in main_window.py:2518-2594; the union is built by
_dashboard_figure_catalog().

**Proposed improvement.** Rename the checkbox to Use one figure selection for
all checked projects and show a visible mode label such as Shared list — 2
checked projects. Add project/source badges to list rows or a small available
in detail when the active project differs from the figure's source.

**Expected benefit.** Shared selection remains efficient for repeated reporting
but no longer looks like an active-project-only list.

**Guardrail.** Keep the current shared/local persistence behaviour and per
project filtering; do not force users into repetitive project-by-project
selection.

### F-11 — Status and output information is valuable but visually dense

Severity: Medium
Type: Visual/layout improvement

**Current behaviour.** The project tree stores comma-separated status chips in a
fixed 180 px Status column. The Preview table stores long semicolon-separated
output folder strings in one cell, with warnings in another. The real sample
project therefore produces a long status string and a long output path string
inside compact tables.

**Problem.** Important state is present but difficult to scan. The status column
can elide several conditions, while the output cell requires reading path
syntax to understand what was produced. This increases the cost of checking a
large project batch.

**Evidence.** The real scan row contained
Ready, No dashboards, Plots exist, Reports exist, High voltage proposals: 78.
The Preview row contained three generated output roots in one cell. The fixed
column width is set in main_window.py:645-656 and preview headers/cells are
defined in main_window.py:957-982.

**Proposed improvement.** Keep the compact table but render statuses as
separate coloured/accessible badges with a summary count, and add a details
panel or tooltip for the full list. Replace the output path string with short
stage badges (Envelope, Plots, Reports) and reveal exact paths on copy/hover.

**Expected benefit.** Users can identify missing or stale stages in seconds
without losing access to exact paths.

**Guardrail.** Do not hide warnings or change the status contract used by
session persistence and reports; the details view must retain the raw text.

### F-12 — Splitter adjustments are not retained for regular users

Severity: Medium
Type: Confirmed workflow-efficiency problem

**Current behaviour.** Users can resize the workspace, left vertical split, and
project/scope splitters. Recreating the window restores the hard-coded initial
sizes rather than the user's layout.

**Problem.** Analysts who repeatedly work with a large project list, a wide
preview table, or a detailed exclusion table must repeat the same layout
adjustments every session.

**Evidence.** The harness changed all three splitter groups, closed the window,
and recreated it. The changed sizes were replaced by the defaults from
main_window.py:416-435.

**Proposed improvement.** Persist splitter sizes as app-level UI preferences,
with validation/clamping when the screen geometry changes. Provide a Reset
layout action near the Settings/session controls.

**Expected benefit.** Regular users get back to their preferred working view
without adding steps to the analysis workflow.

**Guardrail.** Persist only layout preferences, not project-specific analysis
state. Clamp invalid sizes and keep a reliable reset path.

### F-13 — Equivalent bulk actions use inconsistent vocabulary

Severity: Low
Type: Consistency and polish problem

**Current behaviour.** Similar controls are labelled All/None in the project
list, Apply all/Apply none in exclusion tables, and Add/Delete in projects,
scopes, manual exclusions, and heatmap sets. Dashboard actions are Scan
figures and Dashboards update, while analysis actions use a mixture of Build,
Rebuild, Create, Render, and Run.

**Problem.** The labels are individually understandable but do not form one
consistent verb-object vocabulary. The short labels are particularly ambiguous
when several groups are visible at once.

**Evidence.** The widget labels are visible in the rendered main/settings
states and are constructed in main_window.py:622-686,
main_window.py:690-858, main_window.py:897-946, and
settings_dialog.py:471-474.

**Proposed improvement.** Standardize bulk actions as Select all/Clear all, use
Remove from session for project deletion, and reserve Rebuild for an action
that regenerates an existing artifact. Keep the domain terms SFO, TOV, SA, and
SDPF but add expanded text in group labels or help.

**Expected benefit.** Users build a reusable vocabulary and make fewer
wrong-target clicks without adding much screen space.

**Guardrail.** Preserve established output semantics: Run analysis must remain
the connected path, while narrow rebuild operations remain explicit.

## Positive decisions to retain

- The semantic light/dark theme is centralized in styles.py; Run and Stop
  actions have distinct visual roles, selected and disabled controls have
  dedicated colours, and the application responds to the Windows colour
  scheme. The UI/theme test suite passed 38 tests, including contrast
  assertions and checkbox painting. Keep this system and refine it centrally.
- The project header and Dashboard Figures header follow the active project,
  and project paths are available as tooltips. Keep this context model while
  making active-versus-checked state more explicit.
- The background-task lock, Stop action, cancellation messages, and
  close-while-busy behaviour are safer than allowing edits during a write.
  Improve progress detail without weakening the lock.
- The Missing Um recovery dialog offers Open Settings at the point of failure.
  This is a good contextual recovery pattern and should be reused for other
  blocking configuration errors.
- Preview, dashboard selection, and log are colocated in the right-hand
  workspace, which gives experienced users a useful monitoring area. Improve
  density and empty states rather than removing it.
- Conditional NonConv and High Voltage tabs prevent irrelevant empty technical
  tables from dominating every project. If they remain conditional, explain
  why a tab is absent when a user expects proposal data.

## Prioritization

### High-value fixes

1. F-01 — Add a first-run empty state and gate/clarify actions with no
   selected work.
2. F-02 — Give RMS a visible enable label and an explicit configure action.
3. F-03 — Explain active project versus checked projects.
4. F-04 — Create a clear primary action path and disambiguate duplicate stage
   labels.
5. F-05 — Add determinate stage/project/scope progress.
6. F-06 — Introduce a usable narrow-layout mode.
7. F-08 — Make editable engineering cells validate visibly before acceptance.

### Worthwhile improvements

1. F-07 — Separate routine/project-scoped settings from advanced constants.
2. F-09 — Replace Apply with explicit exclusion/override language.
3. F-10 — Make shared dashboard figure mode and source projects visible.
4. F-11 — Turn dense status/output strings into scannable summaries with
   details on demand.
5. F-12 — Persist splitter layout with a reset action.

### Optional polish

1. F-13 — Standardize bulk-action vocabulary and stage verbs.
2. Add consistent visible unit/help text to table headers where the current
   tooltip-only explanation is still required after F-08.
3. Recheck hit-target sizes, typography, and native file-dialog presentation
   on Windows after the responsive work, because the offscreen harness cannot
   validate those details.

### Keep as-is

1. The centralized semantic light/dark theme and checkbox treatment.
2. The active-project context propagation and project-specific state isolation.
3. The background worker, Stop, cancellation, and close-while-busy safety
   model.
4. The contextual Missing Um recovery path.
5. The preview/log monitoring area and conditional proposal tabs, with the
   clarity improvements above.

Other than the spin-box arrow correction documented above, no findings from
this audit have been implemented. The remaining recommendations are intended
to be discussed and prioritized before a broader production UI update.
