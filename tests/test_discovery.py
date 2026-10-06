import unittest

from app.agents.discovery import run_discovery
from app.agents.policy import approval_required
from app.agents.sources import OfflineSignalProvider, SignalBundle


class DiscoveryTests(unittest.TestCase):
    def test_offline_run_is_labeled_and_has_stable_lead_ids(self):
        first = run_discovery("Find field force prospects")
        second = run_discovery("Find field force prospects")

        self.assertEqual(first.data_mode, "offline_synthetic")
        self.assertEqual(len(first.leads), 4)
        self.assertEqual(
            [lead.lead_id for lead in first.leads],
            [lead.lead_id for lead in second.leads],
        )
        self.assertTrue(all(
            source["data_mode"] == "offline_synthetic"
            for lead in first.leads
            for source in lead.sources
        ))
        self.assertFalse(first.outreach_performed)
        self.assertEqual(first.persistence, "not_configured")

    def test_do_not_contact_fixture_is_flagged(self):
        result = run_discovery("Find field force prospects")
        blocked = next(lead for lead in result.leads if lead.do_not_contact)

        self.assertEqual(blocked.company, "Blocked ExampleCorp")
        self.assertEqual(blocked.status, "DO_NOT_CONTACT")
        self.assertEqual(blocked.recommended_next_step, "do_not_contact_review")

    def test_do_not_contact_uses_exact_hostname_matching(self):
        class OneCandidateProvider:
            data_mode = "offline_test"

            def __init__(self, website: str):
                self.candidate = SignalBundle(
                    company="Hostname test",
                    website=website,
                    industry="Test",
                    geography="Test",
                    signals=(),
                )

            def search(self, query: str, limit: int = 10):
                return [self.candidate]

        exact_domain = run_discovery(
            "test",
            provider=OneCandidateProvider("https://blocked-example.com/path"),
        )
        lookalike_domain = run_discovery(
            "test",
            provider=OneCandidateProvider(
                "https://blocked-example.com.attacker.invalid"
            ),
        )

        self.assertTrue(exact_domain.leads[0].do_not_contact)
        self.assertFalse(lookalike_domain.leads[0].do_not_contact)

    def test_product_fit_and_contact_approval_are_explicit(self):
        result = run_discovery("Find field force prospects")
        lead = next(
            lead for lead in result.leads
            if lead.company == "Rajasthan AgriLogistics Pvt Ltd"
        )

        self.assertEqual(lead.product_match, "field_force_management")
        self.assertGreaterEqual(lead.fit_score, 0.30)
        self.assertEqual(
            lead.recommended_next_step,
            "owner_review_required_before_contact",
        )
        self.assertTrue(approval_required("external_sales_outreach"))

    def test_fixture_provider_is_bounded(self):
        provider = OfflineSignalProvider()

        self.assertEqual(len(provider.search("objective", limit=2)), 2)
        with self.assertRaises(ValueError):
            run_discovery(" ")
        with self.assertRaises(ValueError):
            run_discovery("objective", limit=51)


if __name__ == "__main__":
    unittest.main()