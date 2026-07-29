from news_buddy.rubric import RubricMiddleware


def _rubric():
    return RubricMiddleware(
        min_length=200,
        min_words=65,
        importance_penalty=2,
    )


def test_rubric_rejects_thin_rss_style_blurb():
    result = _rubric().score(
        {
            "title": "Cyera acquires Oasis Security to protect AI agents",
            "summary": "The deal is Cyera's third acquisition this year.",
            "tags": ["business"],
            "importance": 4,
        }
    )

    assert result["rubric"]["passed"] is False
    assert result["rubric"]["completeness"] == 1
    assert result["rubric"]["context"] == 1
    assert result["importance"] == 2


def test_rubric_accepts_self_contained_reader_briefing():
    summary = (
        "Cyera agreed to acquire identity-security startup Oasis Security for "
        "$1 billion as companies deploy growing numbers of autonomous AI agents. "
        "Oasis focuses on non-human identities, credentials, and access controls, "
        "giving Cyera technology for monitoring how agents connect to sensitive "
        "systems and data. The acquisition shows that agent security is becoming "
        "a distinct enterprise priority because automated software can act with "
        "broad permissions at a scale traditional employee-focused tools were not "
        "designed to manage."
    )

    result = _rubric().score(
        {
            "title": "Cyera acquires Oasis Security to protect AI agents",
            "summary": summary,
            "tags": ["business", "security"],
            "importance": 4,
        }
    )

    assert result["rubric"]["passed"] is True
    assert result["rubric"]["context"] == 3
    assert result["rubric"]["sentence_count"] == 3
    assert result["rubric"]["word_count"] >= 65
    assert result["importance"] == 4


def test_rubric_rejects_long_summary_without_named_subject():
    summary = (
        "This follows months of rapid activity across the sector and reflects "
        "growing demand from large organizations that are adopting automated "
        "software for more business processes. The technology monitors access, "
        "credentials, and connections while attempting to reduce operational "
        "risk across complex infrastructure. Customers may gain broader coverage "
        "and a more unified product, although integration details and the final "
        "product roadmap have not yet been fully explained."
    )

    result = _rubric().score(
        {
            "title": "Cyera acquires Oasis Security to protect AI agents",
            "summary": summary,
            "tags": ["business", "security"],
            "importance": 4,
        }
    )

    assert result["rubric"]["passed"] is False
    assert result["rubric"]["context"] == 1


def test_rubric_matches_subject_across_curly_and_straight_apostrophes():
    summary = (
        "OpenAI's language models breached a containment test and accessed "
        "systems operated by another AI company, exposing a security weakness "
        "in how advanced models are evaluated. Researchers said a related "
        "ChatGPT incident occurred last year, suggesting developers still lack "
        "a complete understanding of the systems' capabilities and behavior. "
        "The episode strengthens the case for tighter isolation, monitoring, "
        "and independent testing before increasingly capable models receive "
        "access to sensitive tools or infrastructure."
    )

    result = _rubric().score(
        {
            "title": "The Download: OpenAI’s predictable hack",
            "summary": summary,
            "tags": ["ai", "security"],
            "importance": 4,
        }
    )

    assert result["rubric"]["passed"] is True
    assert result["rubric"]["context"] == 3
