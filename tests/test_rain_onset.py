"""Regression gates for isolated rain-onset detection (stdlib unittest)."""
import unittest
from aguayluz.rain_onset import RainPolicy, observe


def sample(t, rate, **overrides):
    return dict(source_id="nws", station_id="verified-station-001",
                municipio_id="72139", source_ref="https://example.org/authoritative/observation",
                observed_at=t, rate_mm_h=rate, **overrides)


class RainOnsetTests(unittest.TestCase):
    def test_confirm_then_replay_does_not_duplicate(self):
        s, e = observe(None, sample("2026-10-17T20:40:00Z", 0.8))
        self.assertIsNone(e)
        s, e = observe(s, sample("2026-10-17T20:45:00Z", 1.2))
        self.assertEqual(e["event_type"], "NEW_RAIN")
        self.assertEqual(e["first_observed_at"], "2026-10-17T20:40:00+00:00")
        s2, again = observe(s, sample("2026-10-17T20:45:00Z", 1.2))
        self.assertIsNone(again)
        self.assertEqual(s, s2)

    def test_dry_reset_and_second_episode(self):
        s = None
        for t, rate in [("2026-10-17T19:00:00Z", 1),
                        ("2026-10-17T19:05:00Z", 1),
                        ("2026-10-17T19:10:00Z", 0),
                        ("2026-10-17T20:10:00Z", 0),
                        ("2026-10-17T20:15:00Z", 2),
                        ("2026-10-17T20:20:00Z", 2)]:
            s, e = observe(s, sample(t, rate))
        self.assertIsNotNone(e)

    def test_sparse_wet_samples_cannot_confirm(self):
        s, _ = observe(None, sample("2026-10-17T19:00:00Z", 1))
        s, e = observe(s, sample("2026-10-17T20:00:00Z", 1))
        self.assertIsNone(e)

    def test_invalid_and_identity_change_fail_closed(self):
        with self.assertRaises(ValueError):
            observe(None, sample("2026-10-17T19:00:00", 1))
        with self.assertRaises(ValueError):
            observe(None, sample("2026-10-17T19:00:00Z", -1))
        with self.assertRaises(ValueError):
            observe(None, sample("2026-10-17T19:00:00Z", float("nan")))
        s, _ = observe(None, sample("2026-10-17T19:00:00Z", 1))
        switched = sample("2026-10-17T19:05:00Z", 1)
        switched["municipio_id"] = "72001"
        with self.assertRaises(ValueError):
            observe(s, switched)

    def test_below_threshold_never_emits(self):
        s = None
        for i in range(3):
            s, e = observe(s, sample(f"2026-10-17T19:{i*5:02d}:00Z", 0.1))
            self.assertIsNone(e)


if __name__ == "__main__":
    unittest.main()
