"""Evidence-only research synthesis for supplied lead sources."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchDraft:
    synthesis: str
    analysis: dict[str, object]
    sources: list[dict[str, object]]


def build_research(company: str, sources: list[dict[str, object]]) -> ResearchDraft:
    unique_sources: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for source in sources:
        url = str(source.get("url", ""))
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_sources.append(source)

    evidence = [
        signal.strip()
        for source in unique_sources
        for signal in str(source.get("snippet", "")).split(";")
        if signal.strip()
    ]
    data_modes = sorted({str(source.get("data_mode", "unspecified")) for source in unique_sources})
    evidence_lines = "\n".join(f"- {signal}" for signal in evidence) or "- No source snippets supplied"
    synthesis = (
        f"Research synthesis: {company}\n"
        f"Evidence supplied:\n{evidence_lines}\n"
        f"Evidence modes: {', '.join(data_modes) if data_modes else 'none'}\n"
        "This synthesis only organizes supplied evidence; it does not independently verify claims."
    )
    return ResearchDraft(
        synthesis=synthesis,
        analysis={
            "source_count": len(unique_sources),
            "signal_count": len(evidence),
            "data_modes": data_modes,
            "needs_human_verification": True,
            "external_research_performed": False,
        },
        sources=unique_sources,
    )