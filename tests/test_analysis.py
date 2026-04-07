import pytest
from src.models.prospect import ProspectState, ProspectCandidate
from src.nodes.analysis import run


def make_state(raw_text: str = "", scripts: list[str] = None) -> ProspectState:
    return ProspectState(
        candidate=ProspectCandidate(name="Test Business", website="https://example.com"),
        raw_text=raw_text,
        detected_scripts=scripts or [],
        contact_form_status="missing",
    )


class TestBookingDetection:
    def test_detects_calendly_in_scripts(self):
        state = make_state(scripts=["https://calendly.com/d/abc123"])
        result = run(state)
        assert result.analysis.has_booking_link is True
        assert result.analysis.booking_tool == "Calendly"

    def test_detects_booksy_in_text(self):
        state = make_state(raw_text="Book your appointment through Booksy today.")
        result = run(state)
        assert result.analysis.has_booking_link is True
        assert result.analysis.booking_tool == "Booksy"

    def test_detects_book_now_phrase(self):
        state = make_state(raw_text="Click here to book now and reserve your spot.")
        result = run(state)
        assert result.analysis.has_booking_link is True

    def test_no_booking(self):
        state = make_state(raw_text="Welcome to our business. Call us today.")
        result = run(state)
        assert result.analysis.has_booking_link is False
        assert result.analysis.booking_tool is None


class TestChatDetection:
    def test_detects_intercom_in_scripts(self):
        state = make_state(scripts=["https://widget.intercom.io/widget/abc123"])
        result = run(state)
        assert result.analysis.has_live_chat is True
        assert result.analysis.chat_provider == "Intercom"

    def test_detects_tidio_in_scripts(self):
        state = make_state(scripts=["https://code.tidio.co/abc.js"])
        result = run(state)
        assert result.analysis.has_live_chat is True
        assert result.analysis.chat_provider == "Tidio"

    def test_detects_live_chat_phrase(self):
        state = make_state(raw_text="Click to chat with us live now.")
        result = run(state)
        assert result.analysis.has_live_chat is True

    def test_no_chat(self):
        state = make_state(raw_text="Contact us by phone or email.")
        result = run(state)
        assert result.analysis.has_live_chat is False


class TestCTAStrength:
    def test_strong_cta_book_free_consultation(self):
        state = make_state(raw_text="Book a free consultation with our team today.")
        result = run(state)
        assert result.analysis.cta_strength == "strong"

    def test_strong_cta_get_free_quote(self):
        state = make_state(raw_text="Get a free quote now — no obligation.")
        result = run(state)
        assert result.analysis.cta_strength == "strong"

    def test_weak_cta_contact_us(self):
        state = make_state(raw_text="Feel free to contact us with any questions.")
        result = run(state)
        assert result.analysis.cta_strength == "weak"

    def test_absent_cta(self):
        state = make_state(raw_text="We are a family-owned business serving the area since 1998.")
        result = run(state)
        assert result.analysis.cta_strength == "absent"

    def test_cta_examples_populated(self):
        state = make_state(raw_text="Book a free consultation with us. Contact us anytime.")
        result = run(state)
        assert len(result.analysis.cta_text_examples) > 0


class TestWebsiteQuality:
    def test_modern_from_react_script(self):
        state = make_state(scripts=["https://cdn.example.com/react.production.min.js"])
        result = run(state)
        assert result.analysis.website_quality == "modern"

    def test_outdated_from_old_copyright(self):
        state = make_state(raw_text="Copyright 2016 All Rights Reserved.")
        result = run(state)
        assert result.analysis.website_quality == "outdated"

    def test_unknown_when_no_signals(self):
        state = make_state(raw_text="Welcome to our plumbing company.")
        result = run(state)
        assert result.analysis.website_quality == "unknown"


class TestMobileUX:
    def test_good_mobile_with_viewport(self):
        state = make_state(raw_text='<meta name="viewport" content="width=device-width, initial-scale=1">')
        result = run(state)
        assert result.analysis.mobile_ux == "good"

    def test_poor_mobile_without_viewport(self):
        state = make_state(raw_text="Welcome to our website. We offer great services.")
        result = run(state)
        assert result.analysis.mobile_ux == "poor"


class TestAfterHoursAndHours:
    def test_detects_24_7(self):
        state = make_state(raw_text="We are available 24/7 for all your needs.")
        result = run(state)
        assert result.analysis.after_hours_handling_visible is True

    def test_detects_hours_of_operation(self):
        state = make_state(raw_text="Hours of operation: Monday to Friday 9am-5pm.")
        result = run(state)
        assert result.analysis.hours_of_operation_listed is True


class TestTrustAndSocial:
    def test_trust_badge_licensed(self):
        state = make_state(raw_text="We are fully licensed and insured contractors.")
        result = run(state)
        assert result.analysis.trust_badges_present is True

    def test_social_links_facebook(self):
        state = make_state(raw_text="Follow us at facebook.com/ourbusiness")
        result = run(state)
        assert result.analysis.social_links_present is True

    def test_review_widget_podium(self):
        state = make_state(scripts=["https://connect.podium.com/widget.js#ORG_TOKEN=abc"])
        result = run(state)
        assert result.analysis.review_widget_present is True

    def test_testimonials_present(self):
        state = make_state(raw_text="Hear what our clients say about working with us.")
        result = run(state)
        assert result.analysis.testimonials_present is True

    def test_trust_signals_detect_professional_credentials(self):
        state = make_state(raw_text="Dr. Jane Smith D.D.S. Family dentistry in Test City.")
        result = run(state)
        assert result.analysis.trust_badges_present is True

    def test_trust_signals_detect_schema_business_type(self):
        state = make_state(scripts=['{"@type":"Dentist","name":"Test City Dentist"}'])
        result = run(state)
        assert result.analysis.trust_badges_present is True


class TestGapDetection:
    def test_all_gaps_on_empty_page(self):
        state = make_state(raw_text="Welcome to our website.")
        result = run(state)
        gaps = result.analysis.identified_gaps
        assert "No online booking" in gaps
        assert "No contact form or contact page detected" in gaps
        assert "No live chat" in gaps
        assert "No email capture" in gaps
        assert "No after-hours coverage visible" in gaps
        assert "No clear CTA" in gaps

    def test_no_gaps_on_full_page(self):
        state = make_state(
            raw_text=(
                "Book a free consultation now. Subscribe to our newsletter. "
                "Contact form available. Chat with us live. "
                "Available 24/7. Hear what our clients say. "
                "We are BBB accredited."
            ),
            scripts=["calendly.com", "tidio"]
        )
        result = run(state)
        gaps = result.analysis.identified_gaps
        assert "No online booking" not in gaps
        assert "No email capture" not in gaps
        assert "No clear CTA" not in gaps

    def test_contact_form_not_detected_from_generic_name_phrase(self):
        state = make_state(
            raw_text=(
                "We want to know your name. We want to know your story. "
                "Schedule your visit by phone."
            )
        )
        result = run(state)
        assert result.analysis.has_contact_form is False
        assert "No contact form or contact page detected" in result.analysis.identified_gaps


class TestErrorHandling:
    def test_empty_state_does_not_crash(self):
        state = make_state(raw_text="", scripts=[])
        result = run(state)
        assert result.analysis is not None
        assert result.errors == []

    def test_analysis_set_on_state(self):
        state = make_state(raw_text="Some business content here.")
        result = run(state)
        assert result.analysis is not None
