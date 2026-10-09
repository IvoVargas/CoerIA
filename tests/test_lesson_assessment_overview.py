from prism.quality import presentation_assessment_overview_issues


def test_lesson_without_assessment_does_not_require_overview():
    state = {"assessment_activities": [], "resource_item_scope": {"kind": "lesson"}}
    assert presentation_assessment_overview_issues(state, []) == []


def test_general_presentation_still_requires_assessment():
    assert presentation_assessment_overview_issues({"assessment_activities": []}, [])


def test_lesson_with_assessment_still_requires_overview():
    state = {
        "assessment_activities": [{"id": "TA1"}],
        "resource_item_scope": {"kind": "lesson"},
    }
    assert presentation_assessment_overview_issues(state, [])
