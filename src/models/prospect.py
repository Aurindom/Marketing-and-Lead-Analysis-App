from __future__ import annotations
import operator
from typing import Annotated, Optional, Literal
from pydantic import BaseModel, Field


class ErrorRecord(BaseModel):
    node: str
    error_type: str
    message: str


class ProspectCandidate(BaseModel):
    name: str
    website: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    place_id: Optional[str] = None


class AnalysisResult(BaseModel):
    has_contact_form: bool = False
    has_booking_link: bool = False
    booking_tool: Optional[str] = None
    has_live_chat: bool = False
    chat_provider: Optional[str] = None
    has_email_capture: bool = False
    cta_strength: Literal["strong", "weak", "absent"] = "absent"
    cta_text_examples: list[str] = Field(default_factory=list)
    website_quality: Literal["modern", "outdated", "unknown"] = "unknown"
    mobile_ux: Literal["good", "poor", "unknown"] = "unknown"
    page_load_signals: Literal["fast", "slow", "unknown"] = "unknown"
    after_hours_handling_visible: bool = False
    hours_of_operation_listed: bool = False
    testimonials_present: bool = False
    review_widget_present: bool = False
    trust_badges_present: bool = False
    blog_or_content_present: bool = False
    social_links_present: bool = False
    team_page_present: bool = False
    identified_gaps: list[str] = Field(default_factory=list)
    analyst_notes: Optional[str] = None


InboundClassification = Literal[
    "likely_manual_receptionist",
    "likely_voicemail_dependent",
    "likely_basic_IVR",
    "likely_AI_assisted",
    "likely_after_hours_automation",
    "likely_no_meaningful_automation",
    "unknown_insufficient_evidence",
]


class InboundHandlingProfile(BaseModel):
    detected_providers: list[str] = Field(default_factory=list)
    classification: InboundClassification = "unknown_insufficient_evidence"
    classification_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    review_signals: list[str] = Field(default_factory=list)
    data_coverage: Literal["sufficient", "partial", "insufficient"] = "insufficient"


class DimensionScore(BaseModel):
    score: float = Field(default=0.0, ge=0.0, le=10.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class ScoredProspect(BaseModel):
    ai_receptionist_likelihood: DimensionScore = Field(default_factory=DimensionScore)
    inbound_automation_maturity: DimensionScore = Field(default_factory=DimensionScore)
    lead_capture_maturity: DimensionScore = Field(default_factory=DimensionScore)
    booking_intake_friction: DimensionScore = Field(default_factory=DimensionScore)
    follow_up_weakness: DimensionScore = Field(default_factory=DimensionScore)
    revenue_leakage_opportunity: DimensionScore = Field(default_factory=DimensionScore)
    ascent_fit_score: DimensionScore = Field(default_factory=DimensionScore)
    suggested_outreach_angle: Optional[str] = None


class ProspectState(BaseModel):
    candidate: ProspectCandidate
    status: Literal["pending", "enriched", "partial", "failed"] = "pending"
    errors: Annotated[list[ErrorRecord], operator.add] = Field(default_factory=list)
    raw_text: Optional[str] = None
    detected_scripts: list[str] = Field(default_factory=list)
    detected_hrefs: str = ""
    has_form_tag: bool = False
    has_email_input: bool = False
    has_submit_control: bool = False
    contact_form_page: Optional[str] = None
    contact_page_url: Optional[str] = None
    playwright_attempted: bool = False
    playwright_used: bool = False
    blocked_http_status: Optional[int] = None
    internal_js_shell_detected: bool = False
    internal_playwright_used: bool = False
    internal_plugin_playwright_attempted: bool = False
    internal_plugin_playwright_used: bool = False
    contact_form_status: Literal["found", "missing", "unknown"] = "unknown"
    contact_form_check_had_errors: bool = False
    internal_contact_check_reason: Optional[str] = None
    page_title: Optional[str] = None
    meta_description: Optional[str] = None
    analysis: Optional[AnalysisResult] = None
    inbound_profile: Optional[InboundHandlingProfile] = None
    scores: Optional[ScoredProspect] = None
    tier: Optional[Literal["HOT", "WARM", "COLD", "NO_WEBSITE"]] = None
    quality_flags: list[str] = Field(default_factory=list)
    skip_scoring: bool = False
    no_website_opportunity: Optional[Literal["HIGH", "MEDIUM", "LOW"]] = None
    output_category: Optional[str] = None
    priority_rank: Optional[int] = None
