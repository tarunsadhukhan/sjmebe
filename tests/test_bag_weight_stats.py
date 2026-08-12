"""compute_bag_weight_stats vs. the real R-08-23 sheet dated 01.07.26.

94 cm x 57 cm, 580 gm/Bag, B.Twill Branded (C.G.), 20 bags, std MR 20%.
The paper footer reads: 549.28 gm / 12.25% / 587.11 gm, (-5.31% LT), (+1.22% HY).
"""

from src.juteSQC.bag_weight import compute_bag_weight_stats

# (observed bag wt gm, MR%) — the sheet's "Bag Wt." and "M.R." columns, rows 1..20.
SHEET = [
    (544, 12.5), (528, 12.0), (499, 12.5), (543, 10.5), (527, 11.5),
    (546, 10.5), (537, 10.0), (564, 12.5), (596, 14.0), (547, 13.0),
    (557, 12.5), (555, 12.5), (550, 11.5), (552, 12.0), (528, 13.0),
    (560, 13.0), (563, 13.0), (567, 13.5), (553, 12.0), (568, 13.0),
]


def test_matches_paper_sheet():
    readings = [{"obs": obs, "mr": mr} for obs, mr in SHEET]
    s = compute_bag_weight_stats(readings, std_bag_weight=580.0, std_mr_pct=20.0, above_wt_gm=585.0)

    assert s["calc_avg_mr"] == 12.25
    assert s["calc_avg_obs_wt"] == 549.2
    assert s["calc_avg_corr_wt"] == 587.08
    assert s["calc_obs_hy_lt_pct"] == -5.31
    assert s["calc_corr_hy_lt_pct"] == 1.22
    # 14 of 20 corrected weights round above 585 gm. (The paper says 65% — it truncated
    # row 7's 585.8 gm to 585 and excluded it.)
    assert s["calc_above_pct"] == 70.0


def test_above_threshold_optional():
    s = compute_bag_weight_stats([{"obs": 544, "mr": 12.5}], 580.0, 20.0)
    assert s["calc_above_pct"] is None
    assert s["calc_obs_stdev"] is None  # sample stdev needs 2+ rows


if __name__ == "__main__":
    test_matches_paper_sheet()
    test_above_threshold_optional()
    print("ok")
