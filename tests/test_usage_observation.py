"""Reported metering failures must hold dispatch without leaking provider data."""

import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc import codex
from hydra_sdlc.runner import usage_allowed
from test_codex import FakeCapabilityClient
from test_runner import complete_capabilities


def bucket(used=20):
    return {"primary": {"usedPercent": used}, "secondary": None}


def metering(**limits):
    return {"ordinaryUsageAllowed": True, **limits}


def capabilities(data):
    result = complete_capabilities()
    result["usage"]["data"] = copy.deepcopy(data)
    return result


class UsageObservationTests(unittest.TestCase):
    def assert_invalid(self, data):
        self.assertFalse(usage_allowed(capabilities(data)))
        with self.assertRaises(ValueError):
            codex._safe_usage(data)

    def probe(self, data):
        client = FakeCapabilityClient()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            codex, "_versions", return_value={
                "sdk_version": codex.SDK_VERSION, "runtime_version": codex.SDK_VERSION,
            },
        ), patch.object(codex, "_new_capability_client", return_value=(client, object)), patch.object(
            client, "request", return_value=copy.deepcopy(data),
        ) as request, patch.object(client, "close", wraps=client.close) as close:
            result = codex._capabilities_probe(directory)
        request.assert_called_once_with("account/rateLimits/read", None, response_model=object)
        close.assert_called_once_with()
        return result

    def test_healthy_bucket_cannot_hide_invalid_reported_bucket(self):
        for invalid in (None, False, 0, "unknown", [], {}, {"primary": None, "secondary": None}):
            for invalid_first in (False, True):
                with self.subTest(invalid=invalid, invalid_first=invalid_first):
                    entries = [("healthy", bucket()), ("unobserved", invalid)]
                    if invalid_first:
                        entries.reverse()
                    self.assert_invalid(metering(rateLimitsByLimitId=dict(entries)))

    def test_valid_window_cannot_hide_malformed_non_null_optional_window(self):
        for name in ("primary", "secondary"):
            other = "secondary" if name == "primary" else "primary"
            for invalid in (False, 0, "unknown", [], {}):
                with self.subTest(window=name, invalid=invalid):
                    self.assert_invalid(metering(rateLimitsByLimitId={
                        "codex": {other: {"usedPercent": 20}, name: invalid},
                    }))

    def test_supplied_invalid_map_cannot_fall_back_to_healthy_legacy(self):
        for invalid in ({}, [], "unknown", 0, False):
            with self.subTest(invalid=invalid):
                self.assert_invalid(metering(rateLimits=bucket(), rateLimitsByLimitId=invalid))

    def test_legacy_is_used_only_when_map_is_absent_or_null(self):
        for limits in ({"rateLimits": bucket()}, {"rateLimits": bucket(), "rateLimitsByLimitId": None}):
            with self.subTest(limits=limits):
                normalized = codex._safe_usage(metering(**limits))
                self.assertTrue(usage_allowed(capabilities(normalized)))

    def test_present_map_controls_dispatch_over_healthy_legacy(self):
        data = metering(rateLimits=bucket(10), rateLimitsByLimitId={
            "codex": {**bucket(93), "spendControlReached": True},
        })
        normalized = codex._safe_usage(data)
        self.assertFalse(usage_allowed(capabilities(normalized)))

    def test_invalid_percentages_are_not_valid_observations(self):
        for used in (None, False, True, "20", float("nan"), float("inf"), -float("inf"), -1, 101):
            for name in ("primary", "secondary"):
                with self.subTest(used=used, window=name):
                    other = "secondary" if name == "primary" else "primary"
                    self.assert_invalid(metering(rateLimitsByLimitId={
                        "healthy": bucket(),
                        "codex": {other: {"usedPercent": 20}, name: {"usedPercent": used}},
                    }))

    def test_native_permission_allows_valid_high_usage_observations(self):
        for used in (80.01, 81, 93, 100):
            with self.subTest(used=used):
                data = metering(rateLimitsByLimitId={"healthy": bucket(), "codex": bucket(used)})
                normalized = codex._safe_usage(data)
                self.assertEqual(normalized["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"], used)
                self.assertTrue(usage_allowed(capabilities(normalized)))

    def test_every_reported_window_and_bucket_accepts_full_observation_range(self):
        data = metering(rateLimitsByLimitId={
            "codex": {"primary": {"usedPercent": 0}, "secondary": {"usedPercent": 100}},
            "other": bucket(100.0),
        })
        self.assertTrue(usage_allowed(capabilities(codex._safe_usage(data))))

    def test_native_spend_control_is_checked_in_every_selected_bucket(self):
        for fields in ({}, {"spendControlReached": None}, {"spendControlReached": False}):
            snapshot = {**bucket(100), **fields}
            for limits in ({"rateLimits": snapshot}, {"rateLimitsByLimitId": {"codex": snapshot}}):
                with self.subTest(limits=limits):
                    self.assertTrue(usage_allowed(capabilities(codex._safe_usage(metering(**limits)))))
        for control in (True, 0, 1, "false", "true", [], {}):
            snapshot = {**bucket(93), "spendControlReached": control}
            for limits in (
                {"rateLimits": snapshot},
                {"rateLimitsByLimitId": {"healthy": bucket(), "codex": snapshot}},
            ):
                with self.subTest(control=control, limits=limits):
                    normalized = codex._safe_usage(metering(**limits))
                    self.assertFalse(usage_allowed(capabilities(normalized)))

    def test_missing_or_null_optional_window_is_not_an_invalid_observation(self):
        for observed in (
            {"primary": {"usedPercent": 20}},
            {"primary": {"usedPercent": 20}, "secondary": None},
            {"primary": None, "secondary": {"usedPercent": 20}},
            {"secondary": {"usedPercent": 20}},
        ):
            with self.subTest(observed=observed):
                normalized = codex._safe_usage(metering(rateLimitsByLimitId={"codex": observed}))
                self.assertTrue(usage_allowed(capabilities(normalized)))
                for name in ("primary", "secondary"):
                    if observed.get(name) is None:
                        self.assertIsNone(normalized["rateLimitsByLimitId"]["codex"][name])

    def test_no_reported_window_cannot_establish_usage(self):
        for unobserved in ({}, {"primary": None}, {"secondary": None}, {"primary": None, "secondary": None}):
            for limits in ({"rateLimits": unobserved}, {"rateLimitsByLimitId": {"codex": unobserved}}):
                with self.subTest(limits=limits):
                    self.assert_invalid(metering(**limits))
        for limits in ({}, {"rateLimits": None, "rateLimitsByLimitId": None}):
            with self.subTest(limits=limits):
                self.assert_invalid(metering(**limits))

    def test_malformed_top_level_response_does_not_establish_usage(self):
        for data in (None, [], "unknown", False, 0):
            with self.subTest(data=data):
                self.assert_invalid(data)

    def test_top_level_credit_claim_does_not_authorize_bucket_usage(self):
        for allowed in (None, False, 1, "true"):
            with self.subTest(allowed=allowed):
                data = {
                    "ordinaryUsageAllowed": allowed,
                    "credits": {"hasCredits": True, "unlimited": True},
                    "rateLimits": bucket(),
                }
                self.assertFalse(usage_allowed(capabilities(codex._safe_usage(data))))

    def test_existing_credits_allow_exhausted_legacy_and_selected_map_buckets(self):
        for used in (93, 100):
            for reason in (None, "rate_limit_reached"):
                paid = {**bucket(used), "credits": {"hasCredits": True},
                        "spendControlReached": False, "rateLimitReachedType": reason}
                for limits in ({"rateLimits": paid},
                               {"rateLimitsByLimitId": {"codex": paid, "other": paid}},
                               {"rateLimits": bucket(), "rateLimitsByLimitId": {"codex": paid}}):
                    with self.subTest(used=used, reason=reason, limits=limits):
                        data = {"ordinaryUsageAllowed": False, **limits}
                        normalized = codex._safe_usage(data)
                        self.assertTrue(usage_allowed(capabilities(data)))
                        self.assertTrue(usage_allowed(capabilities(normalized)))

    def test_paid_permission_needs_each_buckets_credit_and_explicit_spend_observation(self):
        paid = {**bucket(100), "credits": {"hasCredits": True}, "spendControlReached": False}
        denied = [
            {**bucket(100), "spendControlReached": False},
            {**paid, "credits": None},
            {**paid, "credits": {"hasCredits": False}},
            {**bucket(100), "credits": {"hasCredits": True}},
            *({**paid, "spendControlReached": value} for value in (None, True, 0, 1, "false", [], {})),
        ]
        for snapshot in denied:
            for first in (False, True):
                items = [("allowed", paid), ("denied", snapshot)]
                if first:
                    items.reverse()
                for limits in ({"rateLimits": snapshot},
                               {"rateLimits": paid, "rateLimitsByLimitId": dict(items)}):
                    with self.subTest(snapshot=snapshot, first=first, limits=limits):
                        data = {"ordinaryUsageAllowed": False, **limits}
                        self.assertFalse(usage_allowed(capabilities(codex._safe_usage(data))))

    def test_malformed_credit_objects_fail_normalization_even_with_included_usage(self):
        malformed = [False, 0, "available", [], {},
                     *({"hasCredits": value} for value in (None, 0, 1, "true", [], {}))]
        for included in (False, True):
            for credits in malformed:
                with self.subTest(included=included, credits=credits):
                    invalid = {**bucket(100), "credits": credits, "spendControlReached": False}
                    self.assert_invalid({"ordinaryUsageAllowed": included,
                        "rateLimitsByLimitId": {"healthy": {**bucket(), "credits": {"hasCredits": True},
                                                               "spendControlReached": False}, "invalid": invalid}})

    def test_workspace_and_unknown_limit_reasons_hold_both_permission_paths(self):
        denials = ("workspace_owner_credits_depleted", "workspace_member_credits_depleted",
                   "workspace_owner_usage_limit_reached", "workspace_member_usage_limit_reached",
                   "future_reason", "", False, 0, [], {})
        for included in (False, True):
            for reason in denials:
                denied = {**bucket(100), "credits": {"hasCredits": True},
                          "spendControlReached": False, "rateLimitReachedType": reason}
                allowed = {**denied, "rateLimitReachedType": None}
                for limits in ({"rateLimits": denied},
                               {"rateLimitsByLimitId": {"allowed": allowed, "denied": denied}}):
                    with self.subTest(included=included, reason=reason, limits=limits):
                        data = {"ordinaryUsageAllowed": included, **limits}
                        self.assertFalse(usage_allowed(capabilities(data)))
                        self.assertFalse(usage_allowed(capabilities(codex._safe_usage(data))))

    def test_included_usage_keeps_optional_credit_and_spend_behavior(self):
        for credits in (None, {"hasCredits": False}, {"hasCredits": True}):
            for control in (None, False):
                for reason in (None, "rate_limit_reached"):
                    with self.subTest(credits=credits, control=control, reason=reason):
                        data = metering(rateLimits={**bucket(100), "credits": credits,
                            "spendControlReached": control, "rateLimitReachedType": reason})
                        self.assertTrue(usage_allowed(capabilities(codex._safe_usage(data))))

    def test_bucket_credits_do_not_replace_known_included_permission_or_capabilities(self):
        paid = {**bucket(100), "credits": {"hasCredits": True}, "spendControlReached": False}
        for included in (None, 0, 1, "false", "true", [], {}):
            with self.subTest(included=included):
                data = {"ordinaryUsageAllowed": included, "rateLimits": paid}
                self.assertFalse(usage_allowed(capabilities(codex._safe_usage(data))))
        data = {"ordinaryUsageAllowed": False, "rateLimits": paid}
        for field, value in (("available", False), ("cleanup", "unknown"), ("sdk_version", None),
                             ("runtime_version", None), ("account", {"status": "unknown"}),
                             ("models", {"status": "known", "ids": []})):
            with self.subTest(field=field):
                self.assertFalse(usage_allowed({**capabilities(codex._safe_usage(data)), field: value}))

    def test_paid_probe_retains_only_credit_permission_and_never_private_balance(self):
        raw = {"ordinaryUsageAllowed": False, "rateLimitsByLimitId": {"codex": {
            **bucket(100), "spendControlReached": False, "rateLimitReachedType": "rate_limit_reached",
            "credits": {"hasCredits": True, "balance": "synthetic-private-credit-balance",
                        "unlimited": True, "accountId": "synthetic-credit-account"},
        }}}
        result = self.probe(raw)
        self.assertEqual(result["usage"]["status"], "known")
        self.assertEqual(result["usage"]["data"]["rateLimitsByLimitId"]["codex"]["credits"],
                         {"hasCredits": True})
        self.assertTrue(usage_allowed(result))
        encoded = json.dumps(result)
        for private in ("balance", "unlimited", "accountId", "synthetic-private-credit-balance",
                        "synthetic-credit-account"):
            self.assertNotIn(private, encoded)
        raw["rateLimitsByLimitId"]["codex"]["credits"]["hasCredits"] = "true"
        rejected = self.probe(raw)
        self.assertEqual(rejected["usage"], {"status": "unknown", "error_type": "ValueError"})
        self.assertFalse(usage_allowed(rejected))
        self.assertNotIn("synthetic-private-credit-balance", json.dumps(rejected))

    def test_normalization_only_keeps_metering_whitelist_without_mutating_input(self):
        window = {
            "usedPercent": 20, "windowDurationMins": 300, "resetsAt": 1234567890,
            "email": "hidden@example.test", "accessToken": "synthetic-window-secret",
        }
        snapshot = {
            "limitId": "codex", "limitName": "Codex", "rateLimitReachedType": None,
            "spendControlReached": False, "primary": window, "secondary": None,
            "accountId": "synthetic-account", "debug": {"token": "synthetic-bucket-secret"},
        }
        data = metering(rateLimits=copy.deepcopy(snapshot), rateLimitsByLimitId={"codex": snapshot})
        data.update(accountId="synthetic-root-account", accessToken="synthetic-root-secret")
        original = copy.deepcopy(data)
        normalized = codex._safe_usage(data)
        self.assertEqual(data, original)
        self.assertEqual(set(normalized), {"ordinaryUsageAllowed", "rateLimits", "rateLimitsByLimitId"})
        for result in (normalized["rateLimits"], normalized["rateLimitsByLimitId"]["codex"]):
            self.assertEqual(set(result), {
                "limitId", "limitName", "rateLimitReachedType", "spendControlReached", "primary", "secondary",
            })
            self.assertEqual(result["primary"], {"usedPercent": 20, "windowDurationMins": 300, "resetsAt": 1234567890})
            self.assertIsNone(result["secondary"])
        serialized = json.dumps(normalized)
        for hidden in ("hidden@example.test", "synthetic-account", "synthetic-bucket-secret",
                       "synthetic-window-secret", "synthetic-root-account", "synthetic-root-secret"):
            self.assertNotIn(hidden, serialized)

    def test_probe_reports_malformed_metering_as_unknown_and_still_closes_client(self):
        bad_responses = [
            metering(rateLimitsByLimitId={"healthy": bucket(), "invalid": invalid})
            for invalid in (None, "unknown", {})
        ] + [
            metering(rateLimits=bucket(), rateLimitsByLimitId={}),
            metering(rateLimitsByLimitId={"codex": {"primary": {"usedPercent": 20}, "secondary": "unknown"}}),
            metering(rateLimitsByLimitId={"codex": bucket(float("nan"))}),
        ]
        for data in bad_responses:
            with self.subTest(data=data):
                data["accessToken"] = "synthetic-secret-not-for-diagnostics"
                result = self.probe(data)
                self.assertTrue(result["available"])
                self.assertEqual(result["account"]["status"], "known")
                self.assertEqual(result["models"]["status"], "known")
                self.assertEqual(result["usage"], {"status": "unknown", "error_type": "ValueError"})
                self.assertFalse(usage_allowed(result))
                self.assertNotIn("synthetic-secret-not-for-diagnostics", json.dumps(result))

    def test_probe_keeps_valid_optional_null_known(self):
        result = self.probe(metering(rateLimitsByLimitId={"codex": bucket()}))
        self.assertEqual(result["usage"]["status"], "known")
        self.assertIsNone(result["usage"]["data"]["rateLimitsByLimitId"]["codex"]["secondary"])
        self.assertTrue(usage_allowed(result))

    def test_probe_keeps_full_usage_known_and_respects_native_permission(self):
        result = self.probe(metering(rateLimitsByLimitId={"codex": bucket(100)}))
        self.assertEqual(result["usage"]["status"], "known")
        self.assertTrue(usage_allowed(result))


if __name__ == "__main__":
    unittest.main()
