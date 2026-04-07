import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
from dotenv import load_dotenv
from src.models.prospect import ProspectState, ProspectCandidate
from src.nodes.sourcing import search_businesses
from src.graph.pipeline import build_pipeline
from src.utils.audit_logger import log_summary

load_dotenv()


def _check_proxy_env():
    proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]
    for var in proxy_vars:
        val = os.environ.get(var) or os.environ.get(var.lower())
        if val:
            print(f"  [WARN] {var}={val} is set. Clearing for this run to avoid silent failures.")
            os.environ.pop(var, None)
            os.environ.pop(var.lower(), None)


_check_proxy_env()


def _load_pipeline_config() -> dict:
    path = os.path.normpath(os.path.join(os.path.dirname(__file__), "config", "pipeline_config.yaml"))
    with open(path) as f:
        return yaml.safe_load(f)


_PIPELINE_CONFIG = _load_pipeline_config()

TARGETS = [
    {"niche": "dental clinic", "location": "Austin, TX"},
    {"niche": "HVAC contractor", "location": "Austin, TX"},
    {"niche": "law firm", "location": "Austin, TX"},
]

MAX_RESULTS_PER_SEARCH = 5
MAX_WORKERS = _PIPELINE_CONFIG["api"]["max_workers"]


def _run_single(pipeline, business: ProspectCandidate) -> dict:
    state = ProspectState(candidate=business)
    try:
        raw = pipeline.invoke(state)
        result = ProspectState(**raw) if isinstance(raw, dict) else raw
        return {
            "name": result.candidate.name,
            "tier": result.tier,
            "website": result.candidate.website,
            "location": result.candidate.location,
            "phone": result.candidate.phone,
            "rating": result.candidate.rating,
            "review_count": result.candidate.review_count,
            "inbound": result.inbound_profile.classification if result.inbound_profile else "unknown",
            "gaps": result.analysis.identified_gaps if result.analysis else [],
            "flags": result.quality_flags,
            "skip_scoring": result.skip_scoring,
            "no_website_opportunity": result.no_website_opportunity,
            "data_blocked": any(
                f.startswith("Data blocked (HTTP 403/Playwright unavailable)")
                for f in result.quality_flags
            ),
            "errors": [e.message for e in result.errors],
        }
    except Exception as e:
        return {
            "name": business.name,
            "tier": None,
            "website": business.website,
            "location": business.location,
            "inbound": "unknown",
            "gaps": [],
            "flags": [],
            "skip_scoring": False,
            "data_blocked": False,
            "errors": [str(e)],
        }


def run():
    pipeline = build_pipeline()
    all_businesses = []

    for target in TARGETS:
        niche = target["niche"]
        location = target["location"]
        print(f"\nSearching: {niche} in {location}")
        businesses = search_businesses(niche, location, max_results=MAX_RESULTS_PER_SEARCH)
        print(f"  Found {len(businesses)} businesses")
        all_businesses.extend(businesses)

    print(f"\nProcessing {len(all_businesses)} businesses concurrently (workers: {MAX_WORKERS})...")

    all_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_run_single, pipeline, b): b for b in all_businesses}
        for future in as_completed(futures):
            result = future.result()
            flag_str = f" [!] {result['flags'][0]}" if result["flags"] else ""
            print(f"  {result['tier'] or 'UNSCORED'} - {result['name']}{flag_str}")
            all_results.append(result)

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    for tier in ("HOT", "WARM", "COLD"):
        tier_results = [r for r in all_results if r["tier"] == tier and not r["data_blocked"]]
        if tier_results:
            print(f"\n{tier} ({len(tier_results)})")
            for r in tier_results:
                flag_str = f" [!] {r['flags'][0]}" if r["flags"] else ""
                print(f"  {r['name']} - {r['location']}{flag_str}")
                if r["skip_scoring"]:
                    print(f"    Gaps: N/A (insufficient web data)")
                elif r["gaps"]:
                    print(f"    Gaps: {', '.join(r['gaps'][:3])}")

    no_website = [r for r in all_results if r["tier"] == "NO_WEBSITE"]
    if no_website:
        no_website.sort(key=lambda r: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(r.get("no_website_opportunity") or "LOW", 2),
            -(r.get("review_count") or 0),
            -(r.get("rating") or 0.0),
        ))
        print(f"\nNO_WEBSITE - Direct Outreach ({len(no_website)})")
        for r in no_website:
            band = r.get("no_website_opportunity") or "LOW"
            phone = r.get("phone") or "no phone"
            rating = r.get("rating") or 0.0
            review_count = r.get("review_count") or 0
            print(f"  [{band}] {r['name']} - {r.get('location', '')}")
            print(f"    Phone: {phone} | {rating} stars | {review_count} reviews")
            print(f"    Gaps: N/A (no website available)")

    data_blocked = [r for r in all_results if r["data_blocked"]]
    if data_blocked:
        print(f"\nDATA_BLOCKED ({len(data_blocked)})")
        for r in data_blocked:
            flag_str = f" [!] {r['flags'][0]}" if r["flags"] else ""
            print(f"  {r['name']} - {r['location']}{flag_str}")
            print(f"    Gaps: N/A (no web data retrieved)")

    unscored = [r for r in all_results if r["tier"] is None]
    if unscored:
        print(f"\nUNSCORED ({len(unscored)})")
        for r in unscored:
            print(f"  {r['name']} - errors: {r['errors']}")

    print("\nOutput records written to: output/")
    print(f"Total processed: {len(all_results)}")

    log_summary(
        source="run_pipeline",
        total=len(all_results),
        hot=sum(1 for r in all_results if r["tier"] == "HOT" and not r["data_blocked"]),
        warm=sum(1 for r in all_results if r["tier"] == "WARM" and not r["data_blocked"]),
        cold=sum(1 for r in all_results if r["tier"] == "COLD" and not r["data_blocked"]),
        no_website=sum(1 for r in all_results if r["tier"] == "NO_WEBSITE"),
        data_blocked=sum(1 for r in all_results if r["data_blocked"]),
        skipped=sum(1 for r in all_results if r["skip_scoring"] and r["tier"] not in ("NO_WEBSITE",)),
        targets=[f"{t['niche']} / {t['location']}" for t in TARGETS],
    )


if __name__ == "__main__":
    run()
