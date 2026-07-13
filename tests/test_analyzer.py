from verivann.analysis.analyzer import analyze
from verivann.schema import Extracted


def test_research_routing():
    a = analyze(Extracted(title="AI architecture", text="local-first self-hosted automation llm memory"))
    assert a.domain == "research"
    assert a.confidence > 0.4


def test_finance_routing():
    a = analyze(Extracted(title="", text="invest budget tax salary bank"))
    assert a.domain == "finance"


def test_task_proposed_on_action_language():
    a = analyze(Extracted(title="", text="Apply to this job, deadline tomorrow. A todo for research."))
    assert a.action == "task"


def test_never_proposes_memory():
    a = analyze(Extracted(title="", text="buy this now, deadline tomorrow, apply immediately"))
    assert a.action != "memory"


def test_drop_on_trivial_input():
    a = analyze(Extracted(title="", text="hi"))
    assert a.action == "drop"


def test_word_boundary_no_false_positive():
    # "sustain" contains "ai" but must NOT count as a research keyword hit.
    a = analyze(Extracted(title="", text="a sustainable garden with detailed captions everywhere here"))
    assert a.domain == "inbox"
