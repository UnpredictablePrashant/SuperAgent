import os
import tempfile
import unittest

from kendr.persistence import (
    initialize_db,
    insert_heartbeat_event,
    insert_monitor_event,
    list_heartbeat_events,
    list_monitor_events,
    list_monitor_rules,
    upsert_monitor_rule,
)


class MonitoringStoreTests(unittest.TestCase):
    def test_monitor_and_heartbeat_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "workflow.sqlite3")
            initialize_db(db_path)

            upsert_monitor_rule(
                {
                    "rule_id": "rule_1",
                    "created_at": "2026-03-18T00:00:00+00:00",
                    "updated_at": "2026-03-18T00:00:00+00:00",
                    "monitor_type": "stock_price",
                    "name": "AAPL Watch",
                    "subject": "AAPL",
                    "interval_seconds": 300,
                    "channel": "telegram",
                    "recipient": "user1",
                    "config": {"threshold_above": 220},
                    "last_checked_at": "",
                    "last_value": {},
                    "status": "active",
                },
                db_path,
            )
            insert_monitor_event(
                {
                    "event_id": "event_1",
                    "rule_id": "rule_1",
                    "timestamp": "2026-03-18T00:05:00+00:00",
                    "severity": "high",
                    "triggered": True,
                    "title": "AAPL alert",
                    "details": "price crossed threshold",
                    "notification_status": "sent",
                    "metadata": {"price": 221},
                },
                db_path,
            )
            insert_heartbeat_event(
                {
                    "heartbeat_id": "hb_1",
                    "service_name": "kendr-daemon",
                    "timestamp": "2026-03-18T00:10:00+00:00",
                    "status": "ok",
                    "message": "healthy",
                    "metadata": {"configured_services": ["openai"]},
                },
                db_path,
            )

            self.assertEqual(len(list_monitor_rules(db_path=db_path)), 1)
            self.assertEqual(len(list_monitor_events(db_path=db_path)), 1)
            self.assertEqual(len(list_heartbeat_events(db_path=db_path)), 1)


if __name__ == "__main__":
    unittest.main()
