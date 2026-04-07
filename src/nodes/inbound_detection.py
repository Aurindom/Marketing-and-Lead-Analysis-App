import os
import re
import yaml
from src.models.prospect import ProspectState, InboundHandlingProfile, InboundClassification, ErrorRecord

_cfg = None


def _load_config() -> dict:
    global _cfg
    if _cfg is None:
        path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "pipeline_config.yaml"
        ))
        with open(path) as f:
            _cfg = yaml.safe_load(f)["inbound_detection"]
    return _cfg


def _c(key):
    return _load_config()[key]

VOIP_AND_AI_PROVIDERS = {
    "dialpad": "Dialpad",
    "aircall": "Aircall",
    "openphone": "OpenPhone",
    "grasshopper": "Grasshopper",
    "ringcentral": "RingCentral",
    "vonage": "Vonage",
    "nextiva": "Nextiva",
    "goto.com": "GoTo Connect",
    "justcall": "JustCall",
    "smith.ai": "Smith.ai",
    "ruby": "Ruby Receptionists",
    "posh.com": "Posh",
    "gabbyville": "Gabbyville",
    "callrail": "CallRail",
    "invoca": "Invoca",
    "twilio": "Twilio",
    "signalwire": "SignalWire",
    "bland.ai": "Bland AI",
    "synthflow": "Synthflow",
    "vapi.ai": "Vapi",
    "retell": "Retell AI",
    "regal.io": "Regal.io",
}

VOICEMAIL_SIGNALS = [
    "leave a message", "leave us a message", "leave a voicemail",
    "we'll call you back", "we will call you back", "return your call",
    "after the beep", "voicemail",
]

MANUAL_RECEPTIONIST_SIGNALS = [
    "our receptionist", "speak with our receptionist", "front desk",
    "our staff will", "someone will answer", "give us a call and",
    "call during business hours", "available during office hours",
]

AFTER_HOURS_AUTOMATION_SIGNALS = [
    "after hours answering", "after-hours service", "24/7 answering",
    "after hours support", "never miss a call", "always available",
    "calls answered 24", "round-the-clock",
]

IVR_SIGNALS = [
    "press 1 for", "press 2 for", "dial 1 for", "dial 0 for",
    "for sales press", "for support press", "automated menu",
    "phone menu", "automated phone",
]

AI_SIGNALS = [
    "ai receptionist", "virtual receptionist", "ai assistant",
    "automated intake", "ai-powered", "conversational ai",
    "voice ai", "ai answering",
]

NEGATIVE_REVIEW_PATTERNS = [
    r"(couldn't|could not|can't|cannot|hard to|difficult to)\s+(reach|get through|get a hold|contact)",
    r"(never|no one|nobody).{0,10}(answered|picks up|called back|returned)",
    r"(went to|got|goes to)\s+voicemail",
    r"(long|forever|ages|too long)\s+(wait|hold|on hold)",
    r"(phone|call).{0,30}(not working|broken|disconnected|rings out)",
    r"(left|sent).{0,20}(message|voicemail).{0,30}(never|no response|ignored)",
]

POSITIVE_REVIEW_PATTERNS = [
    r"(answered|picked up)\s+(right away|immediately|quickly|fast|promptly)",
    r"(always|someone)\s+(available|answers|picks up)",
    r"(quick|fast|immediate|prompt)\s+(response|reply|callback|turnaround)",
    r"(24.?7|after hours|late|weekend).{0,30}(available|answered|responded|helped)",
]


def run(state: ProspectState) -> ProspectState:
    try:
        all_text = " ".join([
            (state.raw_text or "").lower(),
            " ".join(state.detected_scripts).lower(),
        ])

        providers = _fingerprint_providers(all_text)
        classification, confidence, evidence = _classify(all_text, providers)

        website_signals = _mine_reviews(state.raw_text or "")
        tavily_signals, has_external_reviews = _fetch_tavily_reviews(
            state.candidate.name,
            state.candidate.location or "",
        )

        seen: set[str] = set()
        review_signals: list[str] = []
        for s in website_signals + tavily_signals:
            if s not in seen:
                seen.add(s)
                review_signals.append(s)
        review_signals = review_signals[:10]

        coverage = _assess_coverage(all_text, providers, review_signals, has_external_reviews=has_external_reviews)

        state.inbound_profile = InboundHandlingProfile(
            detected_providers=providers,
            classification=classification,
            classification_confidence=confidence,
            evidence=evidence,
            review_signals=review_signals,
            data_coverage=coverage,
        )
        return state

    except Exception as e:
        state.errors.append(ErrorRecord(
            node="inbound_detection",
            error_type=type(e).__name__,
            message=str(e)
        ))
        return state


def _fingerprint_providers(text: str) -> list[str]:
    found = []
    for key, label in VOIP_AND_AI_PROVIDERS.items():
        if key in text:
            found.append(label)
    return found


def _classify(text: str, providers: list[str]) -> tuple[InboundClassification, float, list[str]]:
    evidence = []
    scores: dict[str, float] = {
        "likely_AI_assisted": 0.0,
        "likely_after_hours_automation": 0.0,
        "likely_basic_IVR": 0.0,
        "likely_manual_receptionist": 0.0,
        "likely_voicemail_dependent": 0.0,
        "likely_no_meaningful_automation": 0.0,
    }

    ai_providers = {"Smith.ai", "Ruby Receptionists", "Posh", "Gabbyville", "Bland AI", "Synthflow", "Vapi", "Retell AI", "Regal.io"}
    voip_providers = {"Dialpad", "Aircall", "OpenPhone", "Grasshopper", "RingCentral", "Vonage", "Nextiva", "GoTo Connect", "JustCall", "Twilio", "SignalWire"}

    for p in providers:
        if p in ai_providers:
            scores["likely_AI_assisted"] += _c("score_ai_provider")
            evidence.append(f"AI/virtual receptionist provider detected: {p}")
        elif p in voip_providers:
            scores["likely_basic_IVR"] += _c("score_voip_provider")
            evidence.append(f"VoIP provider detected: {p}")
        else:
            scores["likely_basic_IVR"] += _c("score_other_provider")
            evidence.append(f"Phone/call tracking provider detected: {p}")

    for signal in AI_SIGNALS:
        if signal in text:
            scores["likely_AI_assisted"] += _c("score_ai_signal")
            evidence.append(f"AI signal in page text: '{signal}'")

    for signal in AFTER_HOURS_AUTOMATION_SIGNALS:
        if signal in text:
            scores["likely_after_hours_automation"] += _c("score_after_hours_signal")
            evidence.append(f"After-hours signal: '{signal}'")

    for signal in IVR_SIGNALS:
        if signal in text:
            scores["likely_basic_IVR"] += _c("score_ivr_signal")
            evidence.append(f"IVR signal: '{signal}'")

    for signal in MANUAL_RECEPTIONIST_SIGNALS:
        if signal in text:
            scores["likely_manual_receptionist"] += _c("score_manual_receptionist_signal")
            evidence.append(f"Manual receptionist signal: '{signal}'")

    for signal in VOICEMAIL_SIGNALS:
        if signal in text:
            scores["likely_voicemail_dependent"] += _c("score_voicemail_signal")
            evidence.append(f"Voicemail signal: '{signal}'")

    if not any(s > 0 for s in scores.values()):
        scores["likely_no_meaningful_automation"] = _c("score_no_signal_fallback")
        evidence.append("No inbound handling signals detected on page")

    best = max(scores, key=lambda k: scores[k])
    raw_confidence = min(scores[best], 1.0)

    if raw_confidence < _c("unknown_cutoff"):
        return "unknown_insufficient_evidence", raw_confidence, evidence

    return best, raw_confidence, evidence


def _mine_reviews(text: str) -> list[str]:
    signals = []
    text_lower = text.lower()

    for pattern in NEGATIVE_REVIEW_PATTERNS:
        for match in re.finditer(pattern, text_lower):
            start = max(0, match.start() - 10)
            end = min(len(text_lower), match.end() + 40)
            signals.append("[-] " + text_lower[start:end].strip())
        if len(signals) >= 5:
            break

    for pattern in POSITIVE_REVIEW_PATTERNS:
        for match in re.finditer(pattern, text_lower):
            start = max(0, match.start() - 10)
            end = min(len(text_lower), match.end() + 40)
            signals.append("[+] " + text_lower[start:end].strip())
        if len(signals) >= 8:
            break

    return signals[:8]


def _fetch_tavily_reviews(name: str, location: str) -> tuple[list[str], bool]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return [], False
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        query = f"{name} {location} reviews".strip()
        response = client.search(query=query, max_results=5, search_depth="basic")
        results = response.get("results", [])
        combined = " ".join(r.get("content", "") for r in results)
        has_external = bool(combined.strip())
        return _mine_reviews(combined), has_external
    except Exception:
        return [], False


def _assess_coverage(text: str, providers: list[str], review_signals: list[str], has_external_reviews: bool = False) -> str:
    signal_count = 0
    all_signals = (
        VOICEMAIL_SIGNALS + MANUAL_RECEPTIONIST_SIGNALS +
        AFTER_HOURS_AUTOMATION_SIGNALS + IVR_SIGNALS + AI_SIGNALS
    )
    for s in all_signals:
        if s in text:
            signal_count += 1

    if providers or signal_count >= 2 or len(review_signals) >= 2:
        return "sufficient"
    if has_external_reviews or signal_count == 1 or len(review_signals) == 1:
        return "partial"
    return "insufficient"
