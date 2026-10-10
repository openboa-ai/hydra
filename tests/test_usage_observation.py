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
        data = metering(rateLimits=bucket(10), rateLimitsByLimitId={"codex": bucket(81)})
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

    def test_valid_percentages_above_dispatch_boundary_remain_known_but_blocked(self):
        for used in (80.01, 81, 100):
            with self.subTest(used=used):
                data = metering(rateLimitsByLimitId={"healthy": bucket(), "codex": bucket(used)})
                normalized = codex._safe_usage(data)
                self.assertEqual(normalized["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"], used)
                self.assertFalse(usage_allowed(capabilities(normalized)))

    def test_every_reported_window_and_bucket_accepts_dispatch_boundary(self):
        data = metering(rateLimitsByLimitId={
            "codex": {"primary": {"usedPercent": 0}, "secondary": {"usedPercent": 80}},
            "other": bucket(80.0),
        })
        self.assertTrue(usage_allowed(capabilities(codex._safe_usage(data))))

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

    def test_credits_do_not_replace_explicit_ordinary_usage_permission(self):
        for allowed in (None, False, 1, "true"):
            with self.subTest(allowed=allowed):
                data = {
                    "ordinaryUsageAllowed": allowed,
                    "credits": {"hasCredits": True, "unlimited": True},
                    "rateLimits": bucket(),
                }
                self.assertFalse(usage_allowed(capabilities(codex._safe_usage(data))))

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

    def test_probe_keeps_exhausted_valid_usage_known_without_allowing_dispatch(self):
        result = self.probe(metering(rateLimitsByLimitId={"codex": bucket(100)}))
        self.assertEqual(result["usage"]["status"], "known")
        self.assertFalse(usage_allowed(result))


if __name__ == "__main__":
    unittest.main()
