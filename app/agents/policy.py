"""Approval rules shared by Company OS capabilities."""

APPROVAL_REQUIRED = frozenset({
    "external_sales_outreach",
    "financial_commitment_or_purchase",
    "data_deletion",
    "credential_or_permission_change",
    "production_deployment",
    "sensitive_customer_data_operation",
    "external_publishing_high_risk",
    "proposal_delivery",
    "live_publishing",
    "external_messaging",
})


def approval_required(action: str) -> bool:
    """Return whether an action must pause for explicit owner approval."""
    return action in APPROVAL_REQUIRED