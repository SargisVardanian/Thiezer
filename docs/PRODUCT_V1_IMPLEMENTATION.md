# Thiezer product-v1 implementation contract

Updated 2026-09-06. UI/code: English. This is an implementation brief, not a release claim.

## Delivery boundary

The owner-provided log describes a newer local Flutter/macOS planetarium with catalogue stars, Map/Sky, trajectory controls and joint place/time filtering. The inspected remote baseline is `codex/country-first-planning` at `8c7f301e30aab5e148fe63a0aa3015bf893f15fb`, older than that local work. Preserve the local implementation; do not reset it to this remote snapshot.

This change adds an isolated, deterministic policy module, versioned thresholds and synthetic tests. It does NOT wire the policy into recommendation services, connect global providers, implement route geometry, change the native UI or prove macOS performance. Integrate it against the actual local code behind a feature flag. The owner also receives a fuller specification, a Russian Codex handoff, a launch/revenue plan and an interactive HTML design reference as separate delivery artifacts.

## Product promise

Return an observing opportunity: **a site + a target/profile + a continuous time window + conditions/evidence + access/route**. The product answers where, when, what can be seen and how to get there, rather than independently listing dates and random pins.

Launch directly into Discover, request foreground geolocation with consent and automatically populate useful same-country opportunities. Allow manual location without an account. A current-position pin alone is not success. Keep device location, planning location, search origin, selected site and map camera separate. Delayed GPS must not overwrite a manual plan. Cancel stale location/target/date requests.

## Country-first global behavior

Resolve country/region using versioned geographic boundaries and point-in-polygon checks, with location accuracy and age. IP is only a coarse labeled suggestion. Missing country cannot default to Armenia, 0/0 or worldwide.

Compact country: search the country candidate pool within the travel-time budget. Large/elongated country: local region plus reachable neighboring same-country areas. Area alone is insufficient. The supplied `automatic_scope` only chooses a conservative UX label using configurable extent/area heuristics; production still needs geometry, candidate generation and routing.

Cross-border travel is off by default. Verify the candidate, road-snapped point, parking/walking endpoints AND the complete returned route. Same-country endpoints do not prove the route stays inside. Never silently expand internationally. Worldwide mode is an explicit travel-planning choice and cannot invent cross-ocean car routes.

Scope restricts travel, not environmental light sources: city skyglow across a border still affects a permitted observing site. Handle islands, date-line crossing, DST, polar day/night, uncertain/disputed boundaries and unsupported data explicitly.

## Joint search pipeline

1. Generate bounded, spatially diverse candidates from a geographic index, accessible viewpoints, public observing sites and verified community reports. Intersect country/land/scope/exclusion masks; do not randomly scatter coordinates or invent site names.
2. Screen static darkness, built-up/light sources, slope, terrain/horizon and access. Unknown access remains conditional; known no-entry/closure is rejected. Do not erase every rural candidate merely because an access proxy is weak.
3. For EACH site, compute topocentric Sun/Moon/target geometry and contiguous observing intervals over the selected range. Evaluate the full interval, not the midpoint or the user's original city. Refine crossings and validate ephemeris coverage.
4. Fetch weather/atmosphere only for a shortlist and appropriate model/grid cells. Respect per-variable native coverage, resolution and validity. Preserve partial forecasts. Long-range results are astronomy-only, never fabricated weather.
5. Get real road/trail geometry, duration, access/closures, parking and last-mile information. A routable edge does not prove legal or safe access. If unavailable, retain a provisional site and say route/access unverified. A bearing is not a route.
6. Apply hard blockers before soft ranking. Offer closest-good, earliest-good and best-quality tradeoffs; nearby dates win ties. Do not select a night a year away for general dark sky merely because a scalar score is marginally better.

Strict dark default for non-Sun/Moon targets: Sun center <= -18 degrees, Moon upper limb below the astronomical horizontal plane using documented conventions, target above the terrain horizon with a configurable clearance and minimum continuous duration. A Moon hidden by a mountain is not proof of zero lunar skyglow. Sun and Moon use dedicated profiles: do not require either target below the horizon. Solar mode needs safety handling; near-Sun targets require separate care. An explicit Target-tuned mode may allow twilight/moonlight; never silently enable it.

Best night sky has no single target altitude/azimuth: use null and hide those rows. A defined Milky Way target/region can have its own geometry. Some place/target/range combinations are physically impossible. Explain why and offer the next calculable date or a separate scope/profile; do not invent a date simply to avoid an empty state.

Unknown cloud/air/access/light data cannot become good values. No forward-filled weather beyond validity. PM2.5, aerosol transparency and optical seeing are different metrics. Do not manufacture seeing arcseconds from elevation/humidity. Mountains/coasts receive no automatic quality bonus. Night-light radiance is not measured Bortle/SQM; preserve proxy/model/measurement distinctions and uncertainty.

## Policy integration

Load `configs/opportunity_policy_v1.json` into `Policy`; keep coefficients/version in one place. Defaults are initial product filters, NOT universal physical or medical safety limits and not calibrated probabilities.

`Opportunity.metrics` contains full-interval extrema with units, source/model, issued_at, validity and native resolution. The server adapter must establish those extrema using actual data and documented interpolation/refinement. One valid sample cannot claim two hours of coverage. Geometry evidence must be computed, weather evidence forecast, estimates remain unverified. The client must never be trusted to submit authoritative access/border/hazard booleans.

Statuses: forecast_backed, needs_verification, partial_forecast, astronomy_only, insufficient_data, rejected. Retain reasons and unknowns. Forecast-backed means meets policy according to supplied forecasts, not guaranteed weather or physical safety. The supplied earliest-first ordering separates evidence classes; it is not a scientific quality score. Build/calibrate profile-specific quality scoring separately and expose factor contributions rather than calling scores probabilities.

## Design and actual UI work

Five destinations: Discover / Sky / Places / Community / Saved. Desktop: slim navigation rail, about 340 px results panel, dominant map and contextual detail drawer. Mobile: map, concise controls, draggable result sheet and bottom navigation. Cards/pins/selected sky and time must remain synchronized. Primary card: where, local observing window/timezone, travel time, reasons, data status, Preview sky / Route / Save.

Starting tokens: background #080D14; surface #111A24; elevated #182431; text #F0F4F8; muted #A3B3C3; accent #7BDCC7; warning #F2BE75. Use an 8 px spacing scale, restrained shadows, 12-20 px corners, clear typography and consistent icons. Validate contrast/focus/keyboard/screen-reader behavior, 200% text, reduced motion, small windows and mobile layouts. Do not hide attribution or use color alone for status.

Sky: retain real catalogue-backed positions, realistic angular size, terrain horizon, time scrub, pan/zoom, target direction and altitude. Show separate labeled close-up and astrophotography modes. Never present long-exposure galaxies as naked-eye visibility. Do not use random decorative stars in the scientific renderer. Test GPU backends and map SDKs before replacement; desktop support of a chosen Flutter plugin must be proven, not assumed.

Required states: progressive/cancellable loading, partial result, forecast unavailable, stale location/forecast, permission denied, offline plan, provider failure/quota, target below horizon, no astronomical night, no route, access unknown, no posts, upload pending moderation. Every empty state explains what was actually searched and what can change without silently relaxing constraints.

## Places and community

Places: public observatories, planetariums, science/space museums, optics/telescope shops, relevant events and observing-friendly stays. Record source IDs, category, official public contact/site, hours, visit access, last checked date and attribution. Do not invent stock/prices/hours or assume every observatory is open to visitors. Deduplicate and mark unverified categories. Sponsored listings are labeled and cannot improve sky-quality ranks.

Community starts as an observation journal, not a full social network. Store site, observing date/time, target, equipment/exposure/stacking, processing, report and image rights. Separate naked-eye, astrophotograph and composite. Previous reports do not verify today's weather/access. Seed real contributions with permission; no fake users/reviews/photos.

Exact location private by default; explicit public precision, EXIF stripping on public derivatives, preview, delayed posting, reporting/blocking/removal and deletion. No live user-location broadcast. Uploads need auth, size/type limits, safe re-encoding, moderation state, quotas and abuse handling. Do not launch an unmoderated public feed.

## Platform and operational requirements

Keep Flutter + Python/Skyfield and the modular monolith. External providers use interfaces, timeouts, bounded retries, cancellation, cache validity, quotas, attribution and versioned fixtures. Keep actual astronomy/geography/routing out of LLM generation. Reuse current storage and add infrastructure only for a demonstrated need.

Verify macOS first, then web/PWA and mobile clients with explicit capability tests. Source portability does not prove maps, location, shaders, offline storage or billing on each platform. Production uses hosted HTTPS API, not the developer's localhost. Offline saved packages need permitted map/route assets plus clearly stale forecast data. Minimize raw GPS analytics and define retention/deletion.

## Phases and acceptance

P0: preserve/reproduce current local app, baseline tests, integrate policy adapter under flag, complete start -> automatic results -> details -> site-specific Sky -> real route -> saved/reopened plan.

P1: data-backed global boundaries/candidates, continuous astronomy/weather windows, real routing, actual Flutter design migration and read-only Places. Profile and visually inspect the real Mac application.

P2: real observation journal, privacy/moderation, closed beta with varied geography and field feedback.

P3: hosted deployment, licences, monitoring/backups/restore, distribution/signing, support/privacy/deletion, then payment entitlements and sandbox purchase/cancel/refund/restore tests. Paid services and publication need owner approval.

Required tests: restricted-country destination; route exits/re-enters same country; post-snap boundary; unknown route/access; closure/hazard; small/large/elongated country; islands; date line; DST; polar day/night; never-rising target; target behind terrain; Sun/Moon profiles; missing/expired air while cloud forecast exists; no midpoint-only evidence; stale response race; provider quota/outage; API restart; map/card click synchronization; keyboard/text-scale/small-screen UI.

Cross-check astronomy with independent reference settings (same observer, time scales, refraction/apparent convention). Prior 0.1-degree / two-minute flat-horizon goals are acceptance targets, not achieved accuracy claims. Report actual profile FPS and device; do not claim 60 FPS from a build or Python tests.

## Launch and revenue

Position around a useful, evidence-backed observing trip, not a generic planetarium. Validate with real recent observers, then a small closed beta and actual saved/completed trips. Recruit real clubs/photographers/public observatories, publish honest use cases, keep SEO pages useful and public plans privacy-safe. Do not buy acquisition before repeat use and willingness to pay are visible.

Start Free + Pro. Free keeps basic discovery and all safety/provenance/privacy information. Pro can add multi-site/night comparisons, useful forecast-change alerts, sync and licensed offline trip packs. A price experiment could test USD 4.99/month or USD 39/year; these are hypotheses, not validated market rates. Do not sell year-long weather forecasts or unlimited cheap lifetime API access. B2B and clearly disclosed affiliate bookings/equipment come later.

Illustrative gross arithmetic: 300 annual subscribers x USD 39 = USD 11,700/year, or USD 975/month equivalent BEFORE fees/taxes/refunds/data/support/labor. Measure search/API/media cost, contribution margin, retention and acquisition payback. Do not assume a single universal app-store commission.

A normal Stripe merchant account for an Armenia-only entity is not established by international card acceptance; Armenia is absent from the checked direct Stripe country list. Paddle is a candidate subject to supplier/product/payout approval; its exclusions do not list Armenia, but that is not guaranteed onboarding. Native digital purchases follow current storefront-specific rules. Check local accounting/legal obligations rather than assuming a merchant of record removes all business taxes.

## Sources checked 2026-09-06

- Skyfield observer/twilight/events: https://rhodesmill.org/skyfield/almanac.html
- Open-Meteo commercial terms: https://open-meteo.com/en/pricing — free endpoint is non-commercial; commercial licensing and attribution are separate requirements.
- CAMS/Open-Meteo air data: https://open-meteo.com/en/docs/air-quality-api — native horizons/resolution vary; global composition roughly 45 km/five days and Europe roughly 11 km/four days in current docs.
- OSM tiles: https://operations.osmfoundation.org/policies/tiles/ — public-server bulk offline downloads prohibited; no guaranteed production SLA.
- Nominatim: https://operations.osmfoundation.org/policies/nominatim/ — not unrestricted autocomplete/bulk POI infrastructure.
- Routing options/limits: https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/routing-options ; https://openrouteservice.org/restrictions/
- Flutter graphics: https://docs.flutter.dev/ui/design/graphics/fragment-shaders
- MapLibre Flutter desktop caveats: https://flutter-maplibre.pages.dev/docs/getting-started/setup/
- NASA night-light products: https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/
- Existing photography-planning competitor: https://www.photopills.com/
- Stripe availability: https://stripe.com/global
- Paddle supplier restrictions: https://www.paddle.com/help/legal/sanctions/which-countries-are-supported-by-paddle
- Apple UGC/privacy/payments: https://developer.apple.com/app-store/review/guidelines/
- Apple annual membership: https://developer.apple.com/programs/enroll/ — USD 99 listed, regional prices/taxes may differ.

Product design, thresholds, phases and pricing experiments above are proposals, not facts established by these sources. Recheck changing terms before commercial release.
