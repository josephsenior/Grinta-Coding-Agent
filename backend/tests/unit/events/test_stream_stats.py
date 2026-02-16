"""Tests for backend.events.stream_stats — aggregated event stream statistics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from backend.events.stream_stats import get_aggregated_event_stream_stats


class TestGetAggregatedEventStreamStats:
    """Tests for get_aggregated_event_stream_stats function."""

    def test_no_streams_returns_zero_totals(self):
        """Test returns zero totals when no streams exist."""
        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[]):
            stats = get_aggregated_event_stream_stats()
            assert stats["streams"] == 0
            assert stats["enqueued"] == 0
            assert stats["queue_size"] == 0
            assert stats["queue_utilization_pct_avg"] == 0

    def test_single_stream_aggregates_stats(self):
        """Test aggregates stats from a single stream."""
        mock_stream = MagicMock()
        mock_stream.get_backpressure_snapshot.return_value = {
            "enqueued": 100,
            "dropped_oldest": 5,
            "dropped_newest": 3,
            "high_watermark_hits": 2,
            "persist_failures": 1,
            "cache_write_failures": 0,
            "critical_events": 4,
            "critical_queue_blocked": 0,
            "critical_sync_persistence": 2,
            "durable_enqueue_failures": 0,
            "durable_writer_drops": 0,
            "durable_writer_queue_depth": 10,
            "durable_writer_errors": 0,
            "events_per_minute": 60,
            "drops_per_minute": 1,
            "persist_failures_per_minute": 0,
            "queue_utilization_pct": 75,
            "uptime_seconds": 120,
            "queue_size": 150,
        }

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream]):
            stats = get_aggregated_event_stream_stats()

            assert stats["streams"] == 1
            assert stats["enqueued"] == 100
            assert stats["dropped_oldest"] == 5
            assert stats["dropped_newest"] == 3
            assert stats["high_watermark_hits"] == 2
            assert stats["persist_failures"] == 1
            assert stats["cache_write_failures"] == 0
            assert stats["critical_events"] == 4
            assert stats["critical_queue_blocked"] == 0
            assert stats["critical_sync_persistence"] == 2
            assert stats["durable_enqueue_failures"] == 0
            assert stats["durable_writer_drops"] == 0
            assert stats["durable_writer_queue_depth"] == 10
            assert stats["durable_writer_errors"] == 0
            assert stats["events_per_minute"] == 60
            assert stats["drops_per_minute"] == 1
            assert stats["persist_failures_per_minute"] == 0
            assert stats["queue_utilization_pct_avg"] == 75
            assert stats["uptime_seconds_sum"] == 120
            assert stats["queue_size"] == 150

    def test_multiple_streams_sum_statistics(self):
        """Test aggregates and sums stats from multiple streams."""
        mock_stream1 = MagicMock()
        mock_stream1.get_backpressure_snapshot.return_value = {
            "enqueued": 100,
            "dropped_oldest": 5,
            "queue_utilization_pct": 70,
            "queue_size": 150,
            "events_per_minute": 60,
            "uptime_seconds": 120,
        }

        mock_stream2 = MagicMock()
        mock_stream2.get_backpressure_snapshot.return_value = {
            "enqueued": 200,
            "dropped_oldest": 10,
            "queue_utilization_pct": 80,
            "queue_size": 250,
            "events_per_minute": 90,
            "uptime_seconds": 180,
        }

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream1, mock_stream2]):
            stats = get_aggregated_event_stream_stats()

            assert stats["streams"] == 2
            assert stats["enqueued"] == 300  # 100 + 200
            assert stats["dropped_oldest"] == 15  # 5 + 10
            assert stats["queue_size"] == 400  # 150 + 250
            assert stats["events_per_minute"] == 150  # 60 + 90
            assert stats["uptime_seconds_sum"] == 300  # 120 + 180
            # Average utilization: (70 + 80) / 2 = 75
            assert stats["queue_utilization_pct_avg"] == 75

    def test_averages_queue_utilization_across_streams(self):
        """Test correctly averages queue utilization percentage."""
        mock_stream1 = MagicMock()
        mock_stream1.get_backpressure_snapshot.return_value = {
            "queue_utilization_pct": 60,
        }

        mock_stream2 = MagicMock()
        mock_stream2.get_backpressure_snapshot.return_value = {
            "queue_utilization_pct": 90,
        }

        mock_stream3 = MagicMock()
        mock_stream3.get_backpressure_snapshot.return_value = {
            "queue_utilization_pct": 75,
        }

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream1, mock_stream2, mock_stream3]):
            stats = get_aggregated_event_stream_stats()

            # (60 + 90 + 75) / 3 = 75
            assert stats["queue_utilization_pct_avg"] == 75

    def test_handles_missing_keys_with_defaults(self):
        """Test uses 0 as default for missing stat keys."""
        mock_stream = MagicMock()
        # Return only partial stats
        mock_stream.get_backpressure_snapshot.return_value = {
            "enqueued": 100,
            # All other keys missing
        }

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream]):
            stats = get_aggregated_event_stream_stats()

            assert stats["enqueued"] == 100
            assert stats["dropped_oldest"] == 0
            assert stats["persist_failures"] == 0
            assert stats["queue_size"] == 0

    def test_skips_broken_stream_and_continues(self):
        """Test skips stream that raises exception and continues aggregating others."""
        mock_stream1 = MagicMock()
        mock_stream1.get_backpressure_snapshot.side_effect = RuntimeError("Stream broken")

        mock_stream2 = MagicMock()
        mock_stream2.get_backpressure_snapshot.return_value = {
            "enqueued": 50,
            "queue_size": 75,
        }

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream1, mock_stream2]):
            stats = get_aggregated_event_stream_stats()

            # Should only count stream2
            assert stats["streams"] == 1
            assert stats["enqueued"] == 50
            assert stats["queue_size"] == 75

    def test_empty_snapshot_returns_all_zeros(self):
        """Test handles stream returning empty snapshot dict."""
        mock_stream = MagicMock()
        mock_stream.get_backpressure_snapshot.return_value = {}

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream]):
            stats = get_aggregated_event_stream_stats()

            assert stats["streams"] == 1
            assert stats["enqueued"] == 0
            assert stats["dropped_oldest"] == 0
            assert stats["queue_size"] == 0

    def test_critical_events_aggregation(self):
        """Test aggregates critical event counters correctly."""
        mock_stream1 = MagicMock()
        mock_stream1.get_backpressure_snapshot.return_value = {
            "critical_events": 5,
            "critical_queue_blocked": 2,
            "critical_sync_persistence": 3,
        }

        mock_stream2 = MagicMock()
        mock_stream2.get_backpressure_snapshot.return_value = {
            "critical_events": 7,
            "critical_queue_blocked": 1,
            "critical_sync_persistence": 4,
        }

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream1, mock_stream2]):
            stats = get_aggregated_event_stream_stats()

            assert stats["critical_events"] == 12  # 5 + 7
            assert stats["critical_queue_blocked"] == 3  # 2 + 1
            assert stats["critical_sync_persistence"] == 7  # 3 + 4

    def test_durable_writer_stats_aggregation(self):
        """Test aggregates durable writer statistics."""
        mock_stream = MagicMock()
        mock_stream.get_backpressure_snapshot.return_value = {
            "durable_enqueue_failures": 2,
            "durable_writer_drops": 3,
            "durable_writer_queue_depth": 15,
            "durable_writer_errors": 1,
        }

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream]):
            stats = get_aggregated_event_stream_stats()

            assert stats["durable_enqueue_failures"] == 2
            assert stats["durable_writer_drops"] == 3
            assert stats["durable_writer_queue_depth"] == 15
            assert stats["durable_writer_errors"] == 1

    def test_rate_metrics_aggregation(self):
        """Test aggregates per-minute rate metrics."""
        mock_stream1 = MagicMock()
        mock_stream1.get_backpressure_snapshot.return_value = {
            "events_per_minute": 120,
            "drops_per_minute": 5,
            "persist_failures_per_minute": 2,
        }

        mock_stream2 = MagicMock()
        mock_stream2.get_backpressure_snapshot.return_value = {
            "events_per_minute": 180,
            "drops_per_minute": 3,
            "persist_failures_per_minute": 1,
        }

        with patch("backend.events.stream_stats.EventStream.iter_global_streams", return_value=[mock_stream1, mock_stream2]):
            stats = get_aggregated_event_stream_stats()

            assert stats["events_per_minute"] == 300  # 120 + 180
            assert stats["drops_per_minute"] == 8  # 5 + 3
            assert stats["persist_failures_per_minute"] == 3  # 2 + 1
