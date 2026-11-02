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

### Morning refresh reliability

GitHub Actions attempts collection at 07:23, 09:23 and 10:23 Pakistan time. Later attempts skip collection if the published snapshot already completed that Pakistan calendar day, and retry Pages deployment. A collection with fewer than five jobs or over half of reporting sources failing is not published. The Himalayas daily request counter (date and count only) is committed under `.refresh-state` even after collection failures, then restored on the next runner; no paid storage cache or artifacts are used. The configured 80-request UTC-day safety cap counts failed requests as well. A terminated runner or failed counter commit can lose the latest counter, so it is a best-effort guard rather than a provider-enforced quota. No paid fallback exists.

Refresh jobs fetches the published JSON file, not the source APIs. The public page also reloads after returning to a tab after five minutes, and every 30 minutes while visible. Last successful collection uses Pakistan time and warns after 10:45 AM if today's update is missing (or after 26 hours). The local app runs independent scans. GitHub scheduled events may be delayed or dropped, so this setup improves resilience without guaranteeing an exact morning completion. Scheduled workflows may be disabled after 60 days without repository activity.

### Search controls and live status

Refresh jobs loads the published snapshot. Automatic morning collection is triggered independently through the configured free scheduler; GitHub morning schedules remain as backups. Owner tools is not shown in the dashboard. Authorized repository writers can still run the workflow directly on GitHub, subject to a two-hour cooldown and at most three attempts per Pakistan calendar day. Scheduled retries skip after a successful collection that day. Source-specific daily caps remain in place, with no paid fallback. Credentials are never embedded in the public app.

The workflow publishes credential-free search-status.json on the scout-status branch at start, during publishing, and at completion. The browser reads the raw public file once per minute while visible and when refreshing results, without using the GitHub REST API or requiring a token. Unavailable or stale status remains explicit. A completed collection is not shown as loaded until its timestamp matches the published snapshot. The Pages rebuild is requested only when the public collection differs from the repository snapshot.

### Viewed-date groups and pagination

Table and card layouts group jobs by the first recorded viewing day in Pakistan time. Unviewed jobs stay under Not viewed yet. Older browser histories without timestamps remain under Previously viewed, date unavailable; no dates are invented. Opening an older undated-history role records its viewing date from that point onward, while reopening a dated role keeps its original recorded day. Reading dates and collapsed groups stay private in this browser and are never published.

Groups can be expanded or collapsed independently, and their collapsed state survives reloads. At most 12 expanded jobs appear on each page across all groups. Collapsed jobs do not consume page slots. Numbered pages and Previous/Next controls are available at the bottom; filters, sort, priority and layout changes reset to page one. Employer publication dates remain separate in the Date column. Sort order applies within each viewing group; unviewed jobs are shown first, then newest viewing days, then legacy undated history.
