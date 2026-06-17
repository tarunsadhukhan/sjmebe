"""Tests for break-aware worked/OT computation in the bio-attendance pipeline.

Covers _split_worked_break_secs — the pure helper that subtracts intermediate
(OUT, IN) break pairs from the first-IN..last-OUT span — plus the downstream
eSSL work/OT split applied to its result.
"""

from src.hrms.bioAttUpdation import (
    _REGULAR_WORK_SECONDS,
    _split_worked_break_secs,
)


def _s(t: str) -> int:
    """'HH:MM:SS' -> seconds-of-day."""
    h, m, sec = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + sec


def _work_ot(worked_secs: int) -> tuple[int, int]:
    """Mirror the eSSL split used in _process_bprocess_day (with an OUT punch)."""
    work = min(_REGULAR_WORK_SECONDS, worked_secs)
    ot = max(0, worked_secs - _REGULAR_WORK_SECONDS)
    return work, ot


class TestSplitWorkedBreakSecs:
    def test_reported_example_one_break(self):
        """05:54 IN, 13:55 OUT, 18:03 IN, 21:54 OUT — the bug report case.

        Span 16h, one ~4.12h break → 11.87h worked → 8h work + 3.89h OT.
        """
        punches = [_s("05:54:04"), _s("13:55:42"), _s("18:03:12"), _s("21:54:58")]
        first, last = punches[0], punches[-1]
        worked, brk = _split_worked_break_secs(punches, first, last)

        assert brk == _s("18:03:12") - _s("13:55:42")          # 14850s
        assert worked == (last - first) - brk
        assert brk // 60 == 247
        assert worked // 60 == 713

        work, ot = _work_ot(worked)
        assert work // 60 == 480                                # 8h exactly
        assert ot // 60 == 233                                  # 3.89h

    def test_no_break_single_pair(self):
        """Just IN and OUT, no intermediate punches → break 0, worked == span."""
        punches = [_s("09:00:00"), _s("17:30:00")]
        first, last = punches[0], punches[-1]
        worked, brk = _split_worked_break_secs(punches, first, last)
        assert brk == 0
        assert worked == last - first
        assert worked // 60 == 510                              # 8.5h

    def test_two_breaks(self):
        """Two break windows (lunch + tea) are both subtracted."""
        punches = [
            _s("09:00:00"),   # IN
            _s("12:00:00"), _s("12:30:00"),   # 30m lunch break
            _s("15:00:00"), _s("15:15:00"),   # 15m tea break
            _s("18:00:00"),   # OUT
        ]
        first, last = punches[0], punches[-1]
        worked, brk = _split_worked_break_secs(punches, first, last)
        assert brk == 45 * 60                                   # 30 + 15
        assert worked == (last - first) - 45 * 60
        assert worked // 60 == 9 * 60 - 45                      # 9h span − 45m

    def test_odd_intermediate_punch_ignored(self):
        """A single unpaired intermediate punch (missing partner) → no break."""
        punches = [_s("09:00:00"), _s("13:00:00"), _s("18:00:00")]
        first, last = punches[0], punches[-1]
        worked, brk = _split_worked_break_secs(punches, first, last)
        assert brk == 0
        assert worked == last - first                            # degrades to span

    def test_odd_drops_only_the_trailing_unpaired(self):
        """Three intermediate punches: first pair counts, last is dropped."""
        punches = [
            _s("09:00:00"),                  # IN
            _s("12:00:00"), _s("12:30:00"),  # paired break (30m)
            _s("15:00:00"),                  # unpaired → ignored
            _s("18:00:00"),                  # OUT
        ]
        first, last = punches[0], punches[-1]
        worked, brk = _split_worked_break_secs(punches, first, last)
        assert brk == 30 * 60
        assert worked == (last - first) - 30 * 60

    def test_unsorted_input_is_handled(self):
        """Helper sorts internally — punch order in the list must not matter."""
        ordered = [_s("05:54:04"), _s("13:55:42"), _s("18:03:12"), _s("21:54:58")]
        shuffled = [ordered[2], ordered[0], ordered[3], ordered[1]]
        first, last = ordered[0], ordered[-1]
        assert _split_worked_break_secs(shuffled, first, last) == \
            _split_worked_break_secs(ordered, first, last)

    def test_no_out_punch_span_equals_worked(self):
        """no_out_punch path: last_sec is the synthesized sched-out and there
        is a single real punch, so there are no intermediates → worked == span,
        break 0 (matches how _process_bprocess_day treats it)."""
        first = _s("09:00:00")
        last = _s("17:00:00")  # synthesized scheduled out
        worked, brk = _split_worked_break_secs([first], first, last)
        assert brk == 0
        assert worked == last - first

    def test_break_capped_at_span(self):
        """Defensive: break can never exceed the span (worked stays >= 0)."""
        # Construct a degenerate pair whose gap exceeds the span by placing
        # first/last tightly; intermediates outside (first,last) are excluded,
        # so this really exercises the min() cap only when pairs are inside.
        punches = [_s("09:00:00"), _s("09:10:00"), _s("17:00:00"), _s("18:00:00")]
        first, last = punches[0], punches[-1]
        worked, brk = _split_worked_break_secs(punches, first, last)
        assert worked >= 0
        assert brk <= last - first

    def test_crosses_midnight_offset_seconds(self):
        """Night shift: next-day punches arrive as seconds + 24h. A break that
        straddles midnight is still subtracted correctly."""
        first = _s("21:00:00")               # 21:00 IN
        brk_out = _s("23:30:00")             # 23:30 OUT (break)
        brk_in = _s("00:30:00") + 24 * 3600  # 00:30 next-day IN
        last = _s("05:00:00") + 24 * 3600    # 05:00 next-day OUT
        worked, brk = _split_worked_break_secs(
            [first, brk_out, brk_in, last], first, last
        )
        assert brk == 60 * 60                # 23:30 -> 00:30 = 1h
        assert worked == (last - first) - 60 * 60
