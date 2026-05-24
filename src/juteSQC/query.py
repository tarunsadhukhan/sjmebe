"""
SQL query functions for Jute SQC module.
Morrah Weight QC queries.
"""

from sqlalchemy.sql import text


def get_morrah_wt_table_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                mw.trolley_no LIKE :search
                OR mw.inspector_name LIKE :search
                OR im.item_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            mw.morrah_wt_id,
            mw.entry_date,
            mw.trolley_no,
            mw.inspector_name,
            mw.avg_mr_pct,
            mw.calc_avg_weight,
            mw.calc_max_weight,
            mw.calc_min_weight,
            mw.calc_range,
            mw.calc_cv_pct,
            mw.count_lt,
            mw.count_ok,
            mw.count_hy,
            mw.branch_id,
            dm.dept_desc AS department,
            im.item_name AS jute_quality,
            mw.updated_date_time
        FROM jute_sqc_morrah_wt mw
        LEFT JOIN dept_mst dm ON dm.dept_id = mw.dept_id
        LEFT JOIN item_mst im ON im.item_id = mw.item_id
        WHERE mw.co_id = :co_id
        AND mw.active = 1
        {search_filter}
        ORDER BY mw.entry_date DESC, mw.morrah_wt_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_morrah_wt_table_count_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                mw.trolley_no LIKE :search
                OR mw.inspector_name LIKE :search
                OR im.item_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_morrah_wt mw
        LEFT JOIN dept_mst dm ON dm.dept_id = mw.dept_id
        LEFT JOIN item_mst im ON im.item_id = mw.item_id
        WHERE mw.co_id = :co_id
        AND mw.active = 1
        {search_filter}
    """
    return text(sql)


def get_morrah_wt_by_id_query():
    sql = """
        SELECT
            mw.morrah_wt_id,
            mw.co_id,
            mw.branch_id,
            mw.entry_date,
            mw.inspector_name,
            mw.dept_id,
            mw.item_id,
            mw.trolley_no,
            mw.avg_mr_pct,
            mw.weights,
            mw.calc_avg_weight,
            mw.calc_max_weight,
            mw.calc_min_weight,
            mw.calc_range,
            mw.calc_cv_pct,
            mw.count_lt,
            mw.count_ok,
            mw.count_hy,
            mw.updated_date_time,
            dm.dept_desc AS department,
            im.item_name AS jute_quality
        FROM jute_sqc_morrah_wt mw
        LEFT JOIN dept_mst dm ON dm.dept_id = mw.dept_id
        LEFT JOIN item_mst im ON im.item_id = mw.item_id
        WHERE mw.morrah_wt_id = :morrah_wt_id
        AND mw.active = 1
    """
    return text(sql)


def get_morrah_wt_departments_query():
    sql = """
        SELECT dept_id, dept_desc, dept_code
        FROM dept_mst
        WHERE branch_id = :branch_id
        ORDER BY dept_desc
    """
    return text(sql)


def get_morrah_wt_jute_qualities_query():
    sql = """
        SELECT im.item_id, im.item_name, im.item_code
        FROM item_mst im
        JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id
        JOIN item_grp_mst parent ON parent.item_grp_id = igm.parent_grp_id
        WHERE parent.item_type_id = 2
        AND im.co_id = :co_id
        AND (im.active = 1 OR im.active IS NULL)
        ORDER BY im.item_name
    """
    return text(sql)
