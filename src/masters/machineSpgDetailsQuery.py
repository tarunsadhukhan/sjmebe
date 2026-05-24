from sqlalchemy.sql import text


def get_machine_spg_details_list(co_id: int = None):
    """Get list of machine SPG details with related information."""
    sql = """
    SELECT
      msd.mc_spg_det_id,
      msd.mechine_id,
      mm.machine_name,
      msd.speed,
      msd.no_of_spindle,
      msd.weight_per_spindle,
      msd.is_active,
      msd.branch_id,
      bm.branch_name
    FROM mechine_spg_details msd
    LEFT JOIN machine_mst mm ON msd.mechine_id = mm.machine_id
    LEFT JOIN branch_mst bm ON msd.branch_id = bm.branch_id
    WHERE (:search IS NULL
        OR mm.machine_name LIKE :search) 
    ORDER BY msd.mc_spg_det_id
    """
    query = text(sql)
    return query


def get_machine_spg_details_by_id(mc_spg_det_id: int):
    """Get machine SPG details by ID."""
    sql = """
    SELECT 
      msd.mc_spg_det_id,
      msd.mechine_id,
      mm.machine_name,
      msd.speed,
      msd.no_of_spindle,
      msd.weight_per_spindle,
      msd.is_active,
      msd.branch_id,
      bm.branch_name,
      msd.updated_by,
      msd.updated_date_time
    FROM mechine_spg_details msd
    LEFT JOIN machine_mst mm ON msd.mechine_id = mm.machine_id
    LEFT JOIN branch_mst bm ON msd.branch_id = bm.branch_id
    WHERE msd.mc_spg_det_id = :mc_spg_det_id
    """
    query = text(sql)
    return query


def get_machine_list_by_branch(branch_id: int = None):
    """Get list of machines for a branch."""
    sql = """
    SELECT 
      mm.machine_id,
      mm.machine_name,
      mm.mech_code,
      mm.machine_type_id
    FROM machine_mst mm
    WHERE mm.active = 1
    """
    if branch_id:
        sql += " AND mm.dept_id IN (SELECT dept_id FROM dept_mst WHERE branch_id = :branch_id)"
    
    sql += " ORDER BY mm.machine_name"
    query = text(sql)
    return query


def check_machine_spg_code_exists(branch_id: int, machine_id: int, exclude_id: int = None):
    """Check if machine SPG details already exists for a branch and machine."""
    sql = """
    SELECT COUNT(*) as count
    FROM mechine_spg_details
    WHERE branch_id = :branch_id AND mechine_id = :mechine_id
    """
    if exclude_id:
        sql += " AND mc_spg_det_id != :exclude_id"
    
    query = text(sql)
    return query
