WORKFLOW_ORDER = [
    "scope", "ingest", "document_coverage", "facts_issues", "legal_research",
    "citation_verification", "current_law_check", "proposition_verification",
    "evidence_mapping", "draft_report", "final_validation", "human_review",
    "release_for_reliance",
]

DEPENDENCIES = {
    "scope": set(),
    "ingest": {"scope"},
    "document_coverage": {"ingest"},
    "facts_issues": {"document_coverage"},
    "legal_research": {"facts_issues"},
    "citation_verification": {"legal_research"},
    "current_law_check": {"citation_verification"},
    "proposition_verification": {"current_law_check"},
    "evidence_mapping": {"proposition_verification"},
    "draft_report": {"evidence_mapping"},
    "final_validation": {"draft_report"},
    "human_review": {"final_validation"},
    "release_for_reliance": {"human_review"},
}
