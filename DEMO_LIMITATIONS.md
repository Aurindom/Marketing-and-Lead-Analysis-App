# Demo Limitations

Known boundaries, uncertainty states, and manual review paths for the Ascent Intelligence pipeline.

## Contact Form Detection

**What works:** Homepage form detection (DOM, Divi/Elementor plugin markers, iframe embeds), internal-page fallback (up to 4 paths: `/contact-us`, `/contact`, `/request-an-appointment`, `/book`).

**Uncertainty state (`contact_form_status: unknown`):** Occurs when Playwright is unavailable or times out on a page that can't be parsed statically. The gap is suppressed from the output and a quality flag is added. This is not a "no form" finding — it means the check could not be completed, not that the form is absent.

**Manual review path:** Any record with `contact_form_status: unknown` and `contact_form_check_had_errors: true` should be manually visited. The contact-form gap column will be blank rather than flagged.

## Blocked Sites

**What works:** 403/429/503 responses trigger a Playwright fallback. If Playwright retrieves content, the record is scored normally.

**DATA_BLOCKED state:** When both the HTTP fetch and Playwright fail (or Playwright is disabled), the record is classified `DATA_BLOCKED`. It is not scored, not tiered, and appears separately in output. This is not a low-fit signal — it means the site defended against automated access.

**Manual review path:** DATA_BLOCKED records should be manually visited and qualified. The outreach angle cannot be generated without web data.

## NO_WEBSITE Leads

**What it means:** The business has Google Maps data (name, phone, rating, reviews) but no website. The pipeline does not attempt scoring — there is nothing to analyze.

**Opportunity bands:** HIGH (50+ reviews, 4.0+ rating), MEDIUM (10+ reviews, 3.5+ rating), LOW (otherwise). These are based purely on Google data and are not weighted the same as a full 7-dimension score.

**Manual review path:** Call-first workflow. Phone number and rating are the primary signals. These leads are ranked separately from scored leads.

## Inbound Classification

**What works:** Review signal parsing and provider detection from website text and structured data.

**`unknown_insufficient_evidence`:** Returned when neither reviews nor website content contain enough signals to classify the inbound setup. Score defaults to mid-range (5.0) with low confidence. Treat cautiously.

**Manual review path:** A live call or brief research (check if they answer the phone, go to voicemail, or use an IVR) resolves the classification quickly.

## Scoring Confidence

Tier (HOT/WARM/COLD) is a confidence-weighted composite across 7 dimensions. A business can score HOT with moderate confidence across all dimensions, or WARM with high confidence on a subset. The `confidence` field on each dimension score reflects data quality, not business quality.

Low-confidence dimensions (below 0.3) are down-weighted automatically. Records where the average confidence is below threshold receive a quality flag.

## General Boundaries

- Sites using hard anti-bot controls (Cloudflare, DataDome) will block even Playwright.
- Google Maps results are filtered by review count (`max_review_count`, default 500) to avoid established chains. Adjust per search if needed.
- Sourcing returns up to 3 pages (60 candidates max) per query. High-competition markets may surface fewer true independents.
- The LLM-generated `ascent_fit_score` (dim-7) can be unavailable if the Anthropic API is unreachable. The other 6 dimensions still score; dim-7 defaults to 5.0 with 0.0 confidence.
