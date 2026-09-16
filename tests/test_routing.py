#!/usr/bin/env python3
"""Unit tests for cost-aware routing — no network / secrets required."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.policy import (  # noqa: E402
    COST_PROFILES,
    decide_route,
    score_task,
    target_for_tier,
    tier_for_score,
)
from orchestrator.run_night import (  # noqa: E402
    HardwareSnapshot,
    Task,
    preferred_cloud_target,
    route_task,
)


def make_task(**kwargs) -> Task:
    base = dict(
        page_id="x",
        task_id="BLD-1",
        name="demo",
        acceptance="do a thing",
        complexity="Local-safe",
        model_route="Local Hermes",
        repo="demo",
        priority="P2",
    )
    base.update(kwargs)
    return Task(**base)


class ScoreAndTierTests(unittest.TestCase):
    def test_local_safe_low_score(self) -> None:
        s = score_task(make_task(complexity="Local-safe", priority="P2"))
        self.assertLess(s, 30)
        self.assertEqual(tier_for_score(s), "local")

    def test_cloud_only_is_mid_not_premium_by_default(self) -> None:
        t = make_task(
            complexity="Cloud-only",
            priority="P2",
            name="API cleanup",
            acceptance="Tidy endpoints",
        )
        s = score_task(t)
        self.assertGreaterEqual(s, 50)
        self.assertLess(s, 70)
        self.assertEqual(tier_for_score(s), "standard")

    def test_heavy_p0_is_premium(self) -> None:
        t = make_task(
            complexity="Cloud-only",
            priority="P0",
            name="Auth and billing redesign",
            acceptance="Rebuild oauth and payment infra for production",
        )
        s = score_task(t)
        self.assertGreaterEqual(s, 70)
        self.assertEqual(tier_for_score(s), "premium")

    def test_mid_tier_target_is_grok_bot(self) -> None:
        # Default cursor-grok: mid slot is Grok Bot
        self.assertEqual(target_for_tier("standard", assume_keys=True), "Grok Bot")

    def test_cheap_tier_target_is_cursor(self) -> None:
        self.assertEqual(target_for_tier("cheap", assume_keys=True), "Cursor Cloud")

    def test_premium_tier_prefers_cursor(self) -> None:
        self.assertEqual(target_for_tier("premium", assume_keys=True), "Cursor Cloud")

    def test_mid_falls_back_to_cursor_without_grok_bot(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in (
                "ANTHROPIC_API_KEY",
                "XAI_API_KEY",
                "OPENROUTER_API_KEY",
                "AUTOCODE_GROK_DELEGATE_CMD",
                "CURSOR_API_KEY",
                "AUTOCODE_CURSOR_DELEGATE_CMD",
                "AUTOCODE_COST_LADDER",
                "AUTOCODE_COST_PROFILE",
            ):
                os.environ.pop(k, None)
            os.environ["CURSOR_API_KEY"] = "cursor-test"
            os.environ["AUTOCODE_DISABLE_METERED_GROK"] = "1"
            self.assertEqual(target_for_tier("standard", assume_keys=False), "Cursor Cloud")

    def test_cursor_ultra_profile_routes_all_cloud_to_cursor(self) -> None:
        with mock.patch.dict(os.environ, {"AUTOCODE_COST_PROFILE": "cursor-ultra"}, clear=False):
            os.environ.pop("AUTOCODE_COST_LADDER", None)
            self.assertEqual(COST_PROFILES["cursor-ultra"][0], "Cursor Cloud")
            self.assertEqual(target_for_tier("cheap", assume_keys=True), "Cursor Cloud")
            self.assertEqual(target_for_tier("standard", assume_keys=True), "Cursor Cloud")
            self.assertEqual(target_for_tier("premium", assume_keys=True), "Cursor Cloud")

    def test_cursor_grok_profile_ladder(self) -> None:
        with mock.patch.dict(os.environ, {"AUTOCODE_COST_PROFILE": "cursor-grok"}, clear=False):
            os.environ.pop("AUTOCODE_COST_LADDER", None)
            os.environ.pop("AUTOCODE_CLOUD_PREFERENCE", None)
            self.assertEqual(COST_PROFILES["cursor-grok"], ("Cursor Cloud", "Grok Bot", "Human"))
            self.assertEqual(target_for_tier("cheap", assume_keys=True), "Cursor Cloud")
            self.assertEqual(target_for_tier("standard", assume_keys=True), "Grok Bot")

    def test_cloud_preference_swaps_grok_first(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "AUTOCODE_COST_PROFILE": "cursor-grok",
                "AUTOCODE_CLOUD_PREFERENCE": "grok",
            },
            clear=False,
        ):
            os.environ.pop("AUTOCODE_COST_LADDER", None)
            self.assertEqual(target_for_tier("cheap", assume_keys=True), "Grok Bot")
            self.assertEqual(target_for_tier("standard", assume_keys=True), "Cursor Cloud")

    def test_metered_profile_puts_grok_last(self) -> None:
        with mock.patch.dict(os.environ, {"AUTOCODE_COST_PROFILE": "metered"}, clear=False):
            os.environ.pop("AUTOCODE_COST_LADDER", None)
            self.assertEqual(target_for_tier("cheap", assume_keys=True), "Claude")
            self.assertEqual(target_for_tier("standard", assume_keys=True), "Cursor Cloud")
            self.assertEqual(target_for_tier("premium", assume_keys=True), "Cursor Cloud")


class DecideRouteTests(unittest.TestCase):
    def test_local_safe_stays_local(self) -> None:
        d = decide_route(make_task(), assume_keys=True)
        self.assertEqual(d.target, "local")
        self.assertEqual(d.tier, "local")

    def test_medium_cloud_only_goes_grok_bot(self) -> None:
        t = make_task(
            complexity="Cloud-only",
            priority="P2",
            name="Modest API change",
            acceptance="Adjust one handler",
            model_route="Local Hermes",
        )
        d = decide_route(t, assume_keys=True)
        self.assertEqual(d.target, "Grok Bot")
        self.assertEqual(d.tier, "standard")

    def test_heavy_goes_cursor(self) -> None:
        t = make_task(
            complexity="Cloud-only",
            priority="P0",
            name="Kubernetes terraform security migration",
            acceptance="Production architecture refactor across auth billing",
            model_route="Local Hermes",
        )
        d = decide_route(t, assume_keys=True)
        self.assertEqual(d.target, "Cursor Cloud")
        self.assertEqual(d.tier, "premium")

    def test_light_local_fail_escalates_to_cursor_pool(self) -> None:
        t = make_task(complexity="Local-safe", priority="P3")
        d = decide_route(t, local_failures=2, max_local_attempts=2, assume_keys=True)
        self.assertEqual(d.target, "Cursor Cloud")
        self.assertEqual(d.tier, "cheap")

    def test_explicit_model_route_wins(self) -> None:
        t = make_task(complexity="Local-safe", model_route="Claude")
        d = decide_route(t, assume_keys=True)
        self.assertEqual(d.target, "Claude")

    def test_ultra_profile_skips_grok(self) -> None:
        t = make_task(
            complexity="Cloud-only",
            priority="P2",
            name="Mid feature",
            acceptance="Ordinary change",
        )
        with mock.patch.dict(os.environ, {"AUTOCODE_COST_PROFILE": "cursor-ultra"}, clear=False):
            os.environ.pop("AUTOCODE_COST_LADDER", None)
            d = decide_route(t, assume_keys=True)
            self.assertEqual(d.target, "Cursor Cloud")


class RoutingIntegrationTests(unittest.TestCase):
    def test_local_safe_goes_local(self) -> None:
        hw = HardwareSnapshot(8000, 16000, 40.0, 0.5, True)
        self.assertEqual(route_task(make_task(), hw, 0), "local")

    def test_cloud_only_escalates_to_grok_bot(self) -> None:
        hw = HardwareSnapshot(8000, 16000, 40.0, 0.5, True)
        t = make_task(complexity="Cloud-only", priority="P2", name="Simple cloud job")
        with mock.patch.dict(
            os.environ,
            {
                "AUTOCODE_GROK_DELEGATE_CMD": "./scripts/delegate_grok_stub.sh",
                "CURSOR_API_KEY": "test",
                "AUTOCODE_DISABLE_METERED_GROK": "1",
            },
            clear=False,
        ):
            self.assertEqual(route_task(t, hw, 0), "Grok Bot")

    def test_low_ram_escalates(self) -> None:
        hw = HardwareSnapshot(1000, 8000, 40.0, 0.5, True)
        self.assertNotEqual(route_task(make_task(), hw, 0), "local")

    def test_model_route_claude(self) -> None:
        t = make_task(model_route="Claude")
        self.assertEqual(preferred_cloud_target(t), "Claude")

    def test_mid_prefers_grok_bot_when_configured(self) -> None:
        """Cursor key must not steal mid tasks when Grok Bot is on the ladder."""
        hw = HardwareSnapshot(8000, 16000, 40.0, 0.5, True)
        t = make_task(
            complexity="Cloud-only",
            priority="P2",
            name="Ordinary feature",
            acceptance="Add a field",
        )
        with mock.patch.dict(
            os.environ,
            {
                "AUTOCODE_GROK_DELEGATE_CMD": "./scripts/delegate_grok_stub.sh",
                "CURSOR_API_KEY": "cursor-key",
                "AUTOCODE_DISABLE_METERED_GROK": "1",
            },
            clear=False,
        ):
            self.assertEqual(route_task(t, hw, 0), "Grok Bot")


if __name__ == "__main__":
    unittest.main()
