# PavSim 0.1.1 — English and Russian interface

PavSim now starts in English and supports Russian as an additional language.
The **EN/RU** selector in the toolbar changes the current page without a reload.
The same selector is available in plot windows.

## Changes

- Central EN/RU catalog with stable translation keys and English fallback.
- Localized names and descriptions for all 61 registered library blocks,
  all their parameter labels, choices and tooltips, and all 11 categories.
- Localized editor controls, dialogs, port hints, status messages and stock
  API diagnostics, including subsystem, experiment and optimizer validation.
- Localized plot titles, information panels, optimization trial axes and
  default labels from older models and bundled examples.
- Language preference stored under `pavsim.language` in localStorage.
  Existing editor/plot pages on the same origin follow preference changes.
  The browser's language does not affect the first-launch default.
- Open dialogs retain unsaved values when another window changes the language.
  Model IDs, parameters, connections, view state and computed results are retained.
- Application version and HTTP server identification updated to 0.1.1.

## Compatibility and implementation

There are no new Python or JavaScript dependencies. The existing API keys,
block/port/parameter IDs and model JSON structure are unchanged. The server
continues returning its existing metadata and diagnostic strings; presentation
uses the central catalog in `xcos_mini/web/i18n-catalog.js`. The small runtime
in `xcos_mini/web/i18n.js` formats messages and updates displayed text.

Known diagnostic templates are matched at the presentation boundary, including
nested validation details. Numbers and machine identifiers are preserved.
Adding or changing stock diagnostics requires updating the catalog; a coverage
test checks explicit exception messages in the Python source.

Translations never replace model parameter values. Recognized legacy/default
plot titles are translated only for display. Arbitrary user titles remain as
entered. Closing a parameter dialog without editing its translated default
label preserves the original stored value.

The numerical engine, RK4, delay/discrete semantics, optimization algorithms,
user models and five bundled example JSON files are unchanged.

## Verification

- 237 automated tests pass without skips in a clean CPython 3.12 environment;
  Node.js is used for the existing and new frontend harnesses.
- The six smoke scenarios pass, including independent exponential decay and
  oscillator references.
- Twelve new localization tests cover both dictionaries, metadata for all
  registered blocks, stock diagnostic coverage, first launch, persistence,
  English fallback, storage failure, editor state, open dialogs, dynamic
  elements, boundary protection, plots and model/result compatibility.
- All five examples pass EN → RU → Save → Load → EN through the production
  editor handlers. Running their original and reloaded models produces identical
  results, including experiment and optimization reports.
- Real-browser checks are recorded separately in the acceptance report;
  frontend harnesses are not treated as browser acceptance.

## Known limitations

- Persistence requires localStorage. With storage blocked, English is the
  default on a new page and the selection lasts only for that page.
- Preferences are specific to the browser origin: another host or port has
  its own saved language.
- Arbitrary user labels, model names, custom-block text and unexpected OS or
  extension diagnostics are preserved verbatim. Stock labels and diagnostics
  are covered; there is no automatic translation service.
- API clients still receive legacy metadata/error strings. Localization applies
  to the browser UI, not to machine JSON keys or Python/terminal diagnostics.
- Technical identifiers and mathematical symbols (such as `k1`, `p1`, `J`,
  `t_end`, `h`, RK4, IAE and ISE) retain their spelling.
- Other guides and the historical 0.1.0 release notes keep their existing
  language. README is available in both English and Russian.
