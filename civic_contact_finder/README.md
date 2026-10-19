# U.S. Civic Contact Finder

A small Flask web app and JSON API for searching curated U.S. government contacts and state/local service routes. It is designed to be consumed by a browser, Android client, or desktop client; the native clients are not included in this folder.

## Run locally

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5001/>. `python app.py` serves with Waitress, not Flask's development server.

## Production deployment

The repository can run as a hardened single-process API/web service, but is not a one-click public launch. Supply a real domain, HTTPS termination, monitored operational contacts, privacy/support pages, and host-level monitoring and request filtering. Do *not* expose Waitress directly to the public internet.

Install dependencies from `requirements.txt` in a clean environment. Configure these settings in the hosting platform's secret/configuration manager (do *not* commit real values):

```powershell
$env:APP_ENV = "production"
$env:APP_HOST = "127.0.0.1"
$env:PORT = "5001"
$env:LOG_LEVEL = "INFO"
$env:GEOCODER_CONTACT = "civic-finder-ops@your-real-domain.invalid"
$env:TRUSTED_PROXY_COUNT = "1"
$env:PRIVACY_POLICY_URL = "https://your-real-domain.invalid/privacy"
$env:SUPPORT_URL = "https://your-real-domain.invalid/support"
$env:API_RATE_LIMIT_COUNT = "120"
$env:API_RATE_LIMIT_WINDOW_SECONDS = "60"
$env:HSTS_MAX_AGE_SECONDS = "31536000"
$env:WAITRESS_THREADS = "4"
$env:WAITRESS_CONNECTION_LIMIT = "100"
$env:WAITRESS_CHANNEL_TIMEOUT = "30"
# Set only for separately hosted browser clients; exact HTTPS origins, comma-separated.
$env:CORS_ALLOWED_ORIGINS = ""
python app.py
```

These intentionally invalid sample domains must be replaced with real values; production startup rejects `.invalid` contacts/policy/support URLs. Production startup also fails when required contact/policy/support settings, proxy count, CORS origins, numeric limits, or directory data are invalid. `TRUSTED_PROXY_COUNT` must equal the number of trusted reverse proxies that set `X-Forwarded-For` and `X-Forwarded-Proto`; never trust client-supplied forwarding headers without the proxy chain being configured correctly. The proxy must remove incoming forwarded headers and write its own. Bind Waitress to a private interface and firewall it so only the proxy can connect.

The app applies a per-client, in-memory limit to API calls and marks API responses `Cache-Control: no-store`. This limit is shared by threads in one process only. Configure aggregate request limits/WAF rules at the reverse proxy or API gateway as well, especially with multiple workers or replicas. Waitress thread, connection, channel timeout, and request-body limits have bounded defaults and can be tuned through the settings above. `/healthz` is a liveness check; `/readyz` verifies production configuration and curated directory data. HSTS is emitted only on HTTPS requests, so configure TLS and trusted proxy headers before launch. Use `GEOCODER_CONTACT` as a monitored email address; it is sent in the Nominatim User-Agent.

### API contract for Android and desktop clients

- `POST /api/v1/search` with JSON `{ "q": "<issue>", "location": "<optional city or ZIP>", "state": "<optional jurisdiction>" }` returns `{results, location_context, location_query, location_error, state_service, election_info}`. `election_info` includes the next federal general-election date and 90-day reminder-window status, plus official voter-registration and election-calendar links. For a selected or geocoded state/DC, the calendar link is that jurisdiction's U.S. Vote Foundation dates-and-deadlines page; otherwise it falls back to USA.gov. `GET /api/v1/search` remains available for simple issue-only searches; prefer POST whenever sending a location so it is not placed in the URL.
- `GET /api/v1/recalls` returns up to five recent FDA recall notices parsed from FDA's public recall listing, including notice links, product details, and reason when published. It caches successful results for 15 minutes per process and may serve a visibly marked stale cache for up to 24 hours if FDA is unreachable; without usable cached data, it returns HTTP 503 and official source links. This scrape is a convenience summary—not an emergency alert service or comprehensive recall feed.
- `GET /api/v1/state-services` returns the supported jurisdiction names.
- `GET /healthz` checks that the process is responding.
- `GET /readyz` returns curated directory counts after validating required records and, in production mode, operational configuration.

Unversioned `/api/search` and `/api/state-services` aliases are retained for compatibility. Requests are read-only and do not require authentication. For browser-based clients hosted on a different origin, set `CORS_ALLOWED_ORIGINS` to a comma-separated allowlist of exact HTTPS origins (for example, `https://app.example.com`). CORS is disabled by default; do not set `*`. Native Android/desktop HTTP clients generally do not require CORS.

### Location and privacy

Location is optional. When entered, the text is sent to OpenStreetMap's Nominatim geocoder to identify a U.S. state or territory; it is not stored in the directory or intentionally written to application logs. The browser sends it in the POST body rather than the URL. Configure reverse proxies and hosting logs not to capture POST bodies. The app caches results in process memory for up to 24 hours and serializes requests to respect the public service's one-request-per-second policy. For multi-instance/high-volume deployments, use a contracted geocoding provider or self-hosted service instead; the in-process cache/throttle is not shared between replicas. A state may also be selected manually without sending an address to the geocoder.

## Data coverage and limitations

`data/agencies.csv` contains federal contact routes, including the official House representative finder, Senate contact directory, and USA.gov's nonpartisan voter-registration guide. `data/state_services.csv` covers all 50 states, DC, and five inhabited U.S. territories, with official state/territory government, Attorney General finder, EPA environmental agency directory, FEMA location resources, state transportation department, and city/county directory routes.

Voter registration eligibility, documentation, methods, and deadlines vary by state and territory; the app sends users to official jurisdiction-specific instructions rather than collecting voter data. The House ZIP finder identifies current House representation; users should confirm election district details with their state election office, particularly around redistricting or a new Congress.

The election banner defines its federal reminder window as the 90 days before the next federal general Election Day through Election Day itself. Outside that window it displays the next federal general date and reminds users they can register or check their status anytime. State election schedules and deadlines vary and are linked to the current calendar/office lookup instead of being guessed from the federal schedule.

The product-recall panel shows recent notices from FDA's public recall listing and links to the underlying notice; it also links to USDA FSIS recalls (meat, poultry, and processed egg products) and CPSC recalls (other consumer products). FDA says its public-notice page is not a complete list of all recalls. A notice's presence or absence is not proof that a product is or is not recalled, and the app does not determine local distribution or affected lot numbers. Always read the official notice and verify brand, lot/date code, distribution, and current status. The app does not yet aggregate live USDA FSIS or CPSC notices into the panel. The FDA listing is HTML rather than a stable, documented alerts API; upstream changes cause an explicit error or visibly stale data rather than silently presenting an empty result.

These are primarily directory links, not all direct complaint forms. They do not provide a verified address-specific 311 lookup, determine which municipality owns a road, or guarantee an agency will resolve a report. Verify links and jurisdiction before relying on them. Some entries carry explicit link-verification caveats.