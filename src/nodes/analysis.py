import re
from src.models.prospect import ProspectState, AnalysisResult, ErrorRecord

BOOKING_PROVIDERS = {
    "calendly": "Calendly",
    "acuityscheduling": "Acuity Scheduling",
    "squareup.com/appointments": "Square Appointments",
    "booksy": "Booksy",
    "mindbodyonline": "Mindbody",
    "vagaro": "Vagaro",
    "setmore": "Setmore",
    "appointy": "Appointy",
    "simplybook": "SimplyBook",
    "zocdoc": "ZocDoc",
    "opentable": "OpenTable",
}

CHAT_PROVIDERS = {
    "intercom": "Intercom",
    "drift.com": "Drift",
    "tidio": "Tidio",
    "livechatinc": "LiveChat",
    "zendesk": "Zendesk",
    "freshchat": "Freshchat",
    "crisp.chat": "Crisp",
    "tawk.to": "Tawk.to",
    "hubspot": "HubSpot Chat",
    "purechat": "Pure Chat",
}

STRONG_CTA_PATTERNS = [
    r"\bbook (a |an |your )?(free )?(call|consultation|demo|appointment|session)\b",
    r"\bget (a |your )?(free )?(quote|estimate|consultation)\b",
    r"\bschedule (a |your |now)?\b",
    r"\bclaim (your |a )?(free )?\b",
    r"\bstart (your |a )?(free )?\b",
    r"\brequest (a |your )?(free )?(demo|quote|callback)\b",
]

WEAK_CTA_PATTERNS = [
    r"\bcontact us\b",
    r"\blearn more\b",
    r"\bget in touch\b",
    r"\bsend (a |us a )?message\b",
    r"\bfill out (the |our )?form\b",
]

TRUST_SIGNALS = [
    "bbb", "accredited", "certified", "licensed", "insured",
    "award", "featured in", "as seen on", "guarantee", "warranty",
]

CREDENTIAL_PATTERNS = [
    r"\bd\.?\s*d\.?\s*s\.?\b",
    r"\bd\.?\s*m\.?\s*d\.?\b",
    r"\besq\.?\b",
    r"\bj\.?\s*d\.?\b",
    r"\bboard[- ]certified\b",
    r"\bstate[- ]licensed\b",
]

SCHEMA_TRUST_HINTS = [
    "application/ld+json",
    '"@type":"dentist"',
    '"@type":"medicalbusiness"',
    '"@type":"physician"',
    '"@type":"attorney"',
    '"@type":"legalservice"',
    '"@type":"professionalservice"',
]

OUTDATED_SIGNALS = [
    "copyright 2015", "copyright 2016", "copyright 2017", "copyright 2018",
    "built with wordpress 4", "jquery-1.", "jquery-2.",
]

MODERN_SIGNALS = [
    "react", "next.js", "vue", "nuxt", "gatsby", "webflow",
    "framer", "tailwind", "gsap",
]


def run(state: ProspectState) -> ProspectState:
    try:
        text_lower = (state.raw_text or "").lower()
        scripts_combined = " ".join(state.detected_scripts).lower()
        hrefs_combined = (state.detected_hrefs or "").lower()
        all_text = text_lower + " " + scripts_combined + " " + hrefs_combined

        result = AnalysisResult(
            has_contact_form=_has_contact_form(
                text_lower,
                has_form_tag=state.has_form_tag,
                has_email_input=state.has_email_input,
                has_submit_control=state.has_submit_control,
            ),
            has_booking_link=_has_booking(all_text),
            booking_tool=_detect_booking_tool(all_text),
            has_live_chat=_has_chat(all_text),
            chat_provider=_detect_chat_provider(all_text),
            has_email_capture=_has_email_capture(text_lower),
            cta_strength=_score_cta(text_lower),
            cta_text_examples=_extract_cta_examples(text_lower),
            website_quality=_assess_quality(all_text),
            mobile_ux=_assess_mobile(all_text),
            page_load_signals="unknown",
            after_hours_handling_visible=_has_after_hours(text_lower),
            hours_of_operation_listed=_has_hours(text_lower),
            testimonials_present=_has_testimonials(text_lower),
            review_widget_present=_has_review_widget(all_text),
            trust_badges_present=_has_trust_badges(text_lower, all_text),
            blog_or_content_present=_has_blog(text_lower),
            social_links_present=_has_social(all_text),
            team_page_present=_has_team_page(text_lower),
            identified_gaps=_identify_gaps(
                text_lower,
                all_text,
                has_form_tag=state.has_form_tag,
                has_email_input=state.has_email_input,
                has_submit_control=state.has_submit_control,
                contact_form_status=state.contact_form_status,
                contact_page_url=state.contact_page_url,
            ),
        )

        state.analysis = result
        return state

    except Exception as e:
        state.errors.append(ErrorRecord(
            node="analysis",
            error_type=type(e).__name__,
            message=str(e)
        ))
        return state


def _has_contact_form(
    text: str,
    has_form_tag: bool = False,
    has_email_input: bool = False,
    has_submit_control: bool = False,
) -> bool:
    if has_form_tag and (has_email_input or has_submit_control):
        return True
    if has_form_tag and any(kw in text for kw in ["contact", "message", "appointment", "book"]):
        return True

    return any(
        kw in text for kw in [
            "contact form",
            "contact us form",
            "fill out the form below",
            "submit the form below",
            "request an appointment form",
        ]
    )


def _has_booking(text: str) -> bool:
    return any(kw in text for kw in BOOKING_PROVIDERS) or any(kw in text for kw in ["book now", "book an appointment", "schedule now", "schedule a"])


def _detect_booking_tool(text: str) -> str | None:
    for key, label in BOOKING_PROVIDERS.items():
        if key in text:
            return label
    return None


def _has_chat(text: str) -> bool:
    return any(kw in text for kw in CHAT_PROVIDERS) or any(kw in text for kw in ["live chat", "chat with us", "chat now", "chat support"])


def _detect_chat_provider(text: str) -> str | None:
    for key, label in CHAT_PROVIDERS.items():
        if key in text:
            return label
    return None


def _has_email_capture(text: str) -> bool:
    return any(kw in text for kw in ["subscribe", "newsletter", "enter your email", "get updates", "email list", "join our list"])


def _score_cta(text: str) -> str:
    for pattern in STRONG_CTA_PATTERNS:
        if re.search(pattern, text):
            return "strong"
    for pattern in WEAK_CTA_PATTERNS:
        if re.search(pattern, text):
            return "weak"
    return "absent"


def _extract_cta_examples(text: str) -> list[str]:
    examples = []
    all_patterns = STRONG_CTA_PATTERNS + WEAK_CTA_PATTERNS
    for pattern in all_patterns:
        match = re.search(pattern, text)
        if match:
            start = max(0, match.start() - 10)
            end = min(len(text), match.end() + 30)
            snippet = text[start:end].strip()
            if snippet not in examples:
                examples.append(snippet)
        if len(examples) >= 3:
            break
    return examples


def _assess_quality(text: str) -> str:
    if any(kw in text for kw in MODERN_SIGNALS):
        return "modern"
    if any(kw in text for kw in OUTDATED_SIGNALS):
        return "outdated"
    return "unknown"


def _assess_mobile(text: str) -> str:
    if "viewport" in text and "width=device-width" in text:
        return "good"
    if "viewport" not in text:
        return "poor"
    return "unknown"


def _has_after_hours(text: str) -> bool:
    return any(kw in text for kw in ["after hours", "24/7", "24 hours", "available anytime", "always available", "emergency service"])


def _has_hours(text: str) -> bool:
    return any(kw in text for kw in ["monday", "hours of operation", "business hours", "open daily", "open monday", "we are open"])


def _has_testimonials(text: str) -> bool:
    return any(kw in text for kw in ["testimonial", "what our clients say", "what customers say", "hear from our", "client story", "success stor"])


def _has_review_widget(text: str) -> bool:
    return any(kw in text for kw in ["google reviews", "trustpilot", "birdeye", "podium", "grade.us", "reviewtrackers", "reputation.com"])


def _has_trust_badges(text: str, all_text: str = "") -> bool:
    corpus = f"{text} {all_text}".lower()
    if any(kw in corpus for kw in TRUST_SIGNALS):
        return True
    if any(hint in corpus for hint in SCHEMA_TRUST_HINTS):
        return True
    return any(re.search(pattern, corpus) for pattern in CREDENTIAL_PATTERNS)


def _has_blog(text: str) -> bool:
    return any(kw in text for kw in ["blog", "articles", "resources", "insights", "news", "tips and", "how to"])


def _has_social(text: str) -> bool:
    return any(kw in text for kw in ["facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "tiktok.com"])


def _has_team_page(text: str) -> bool:
    return any(kw in text for kw in ["meet the team", "our team", "about us", "meet our", "our staff", "our doctors", "our attorneys"])


def _identify_gaps(
    text: str,
    all_text: str,
    has_form_tag: bool = False,
    has_email_input: bool = False,
    has_submit_control: bool = False,
    contact_form_status: str = "unknown",
    contact_page_url: str | None = None,
) -> list[str]:
    gaps = []
    if not _has_booking(all_text):
        gaps.append("No online booking")
    if contact_form_status == "missing":
        if contact_page_url is not None:
            gaps.append("No web contact form detected (contact page exists)")
        else:
            gaps.append("No contact form or contact page detected")
    elif contact_form_status == "unknown" and not _has_contact_form(
        text,
        has_form_tag=has_form_tag,
        has_email_input=has_email_input,
        has_submit_control=has_submit_control,
    ):
        pass
    if not _has_chat(all_text):
        gaps.append("No live chat")
    if not _has_email_capture(text):
        gaps.append("No email capture")
    if not _has_after_hours(text):
        gaps.append("No after-hours coverage visible")
    if _score_cta(text) == "absent":
        gaps.append("No clear CTA")
    if not _has_testimonials(text):
        gaps.append("No testimonials")
    if not _has_trust_badges(text, all_text):
        gaps.append("No trust signals")
    return gaps
