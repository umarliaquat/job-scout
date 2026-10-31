# Job Scout

Remote design job research with country requirements, publication dates and application evidence. Built for finding jobs that can be applied to from Pakistan.

The public GitHub Pages interface serves a sanitized snapshot. Saved roles, application status and notes stay in the visitor's browser and are not sent to GitHub. Browser storage does not sync between devices and is removed when browser data is cleared.

## Run locally

Use Python 3.11+; no third-party Python packages or paid keys required.

```
python -B scout.py scan
python -B scout.py serve
```

Open http://127.0.0.1:8765/. Sources are configured in sources.json. Gemini and paid APIs are disabled. Public keyless feeds have their own policies and limits. Himalayas discovery is cached 24 hours with an 80-request daily cap; its update timestamp is never treated as original publication. Application checks do not submit anything or bypass access challenges.

## Update Pages

```
python -B scout.py scan
python -B publish.py --output docs
```

Publish the docs folder from the main branch. A scheduled standard Ubuntu GitHub Action refreshes once daily; failed collection leaves the last successful snapshot available. Scheduled runs can be delayed or disabled by GitHub. Public application checks older than 24 hours are marked for recheck in the interface.

## Validation

```
python -B -m unittest discover -s tests -v
node tests/public_runtime.cjs
```

The export uses an explicit field allowlist. It never publishes the private database, resume profile, notes, application states, API tokens, caches or raw source error paths. Public listings include original source attribution and application links. Employer legitimacy and country eligibility need independent review. Small-team claims are self-reported. There are no response probabilities or invented applicant counts.

Inter Tight is self-hosted under the SIL Open Font License; see web/fonts/OFL.txt.

### New arrivals and reading history

The default New arrivals tab establishes the existing collection as a baseline on your first visit. Subsequent snapshots add unseen listing IDs to a persistent unread queue; changed dates and returning IDs do not reset reading history. The queue shows recent Best leads / Worth a chance roles, excludes applied and dismissed roles, and clears a role when you open its details. All listings remains available, with Viewed / Unviewed filters under More filters. New here means newly discovered in this browser, not newly posted by the employer. History is stored only in localStorage, separately from saves and notes. Clearing browser data or switching browsers resets it. The page warns when browser storage cannot be written. A public tab returning to the foreground after five minutes fetches the latest published snapshot.
