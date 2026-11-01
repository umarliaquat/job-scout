import unittest
from datetime import datetime, timezone
from refresh_control import refreshed_today, usage_record, validate

class RefreshControlTests(unittest.TestCase):
    def test_pakistan_calendar_day_and_future_timestamps(self):
        now = datetime(2026, 11, 1, 3, tzinfo=timezone.utc)
        self.assertTrue(refreshed_today({'last_run': {'finished': '2026-10-31T23:00:00+00:00'}}, now))
        self.assertFalse(refreshed_today({'last_run': {'finished': '2026-10-31T18:00:00+00:00'}}, now))
        self.assertFalse(refreshed_today({'last_run': {'finished': '2026-11-02T00:00:00+00:00'}}, now))
        for value in [None, {}, {'last_run': {'finished': 'invalid'}}, {'last_run': {'finished': '2026-11-01'}}]:
            self.assertFalse(refreshed_today(value, now))

    def test_usage_counter_is_sanitized_and_cannot_reset_invalid_counts(self):
        self.assertEqual(usage_record({'date': '2026-11-01', 'requests': 80, 'private': 'excluded'}), {'date': '2026-11-01', 'requests': 80})
        for count in [-1, 101, '0', True]:
            with self.assertRaises(ValueError):
                usage_record({'date': '2026-11-01', 'requests': count})

    def test_degraded_collection_is_not_a_success(self):
        snapshot = {'last_run': {'finished': datetime.now(timezone.utc).isoformat()}, 'jobs': [{}]*5, 'sources': [{'status': 'error'}]*3}
        with self.assertRaises(ValueError): validate(snapshot)
        snapshot['sources'] = [{'status': 'ok'}, {'status': 'error'}]
        validate(snapshot)

if __name__ == '__main__': unittest.main()
