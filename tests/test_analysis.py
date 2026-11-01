from backend.analysis import analyze_conversation


def test_analysis_is_explainable_and_handles_real_estate_signals():
    result = analyze_conversation(
        "I want to buy a 2 BHK in Wakad with a budget of 80 lakh "
        "this year and want a site visit."
    )
    assert result["score"] == 90
    assert result["category"] == "Hot"
    assert result["requirements"]["bhk"] == "2"
    assert result["requirements"]["site_visit"] == "site visit"


def test_analysis_does_not_assign_score_to_empty_conversation():
    result = analyze_conversation("")
    assert result["score"] is None
    assert result["category"] == "Insufficient Data"
