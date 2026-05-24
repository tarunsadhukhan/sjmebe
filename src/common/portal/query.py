from sqlalchemy.sql import text
from sqlalchemy.sql import bindparam
from sqlalchemy.sql.elements import TextClause


def get_roles_tenant(search: str = None):
    sql = f"SELECT role_id, role_name FROM roles_mst where active = 1 "
    query = text(sql)
    return query

def get_co_tenant(search: str = None):
    sql = f"SELECT co_id, co_name FROM co_mst "
    query = text(sql)
    return query

def get_branch_tenant(search: str = None):
    sql = f"SELECT co_id, branch_id, branch_name FROM branch_mst where active = 1 "
    query = text(sql)
    return query

def get_user_role_map_tenant(user_id: int = None):
    """
    Get user role mappings for a specific user.
    The user_id parameter is expected to be provided when executing the query, not when defining it.
    """
    sql = "SELECT user_role_map_id, user_id, role_id, co_id, branch_id FROM user_role_map WHERE user_id = :user_id"
    query = text(sql)
    return query

def get_co_brnach_all():
    sql = f"SELECT cm.co_id, cm.co_name, bm.branch_id, bm.branch_name FROM branch_mst bm LEFT JOIN co_mst cm ON cm.co_id = bm.co_id;"
    query = text(sql)
    return query

def get_submenu_portal():
    sql = f"SELECT menu_id, menu_name FROM menu_mst mm WHERE mm.menu_parent_id IS NOT NULL;"
    query = text(sql)
    return query

def get_submenu_by_branch():
    """
    Get submenus (menus with parent) for each branch based on actual relationships:
    branch → user_role_map → role_menu_map → menu_mst
    Returns distinct menu_id, menu_name, and branch_id for submenus that are accessible via roles in each branch.
    """
    sql = """
        SELECT DISTINCT 
            bm.branch_id,
            mm.menu_id,
            mm.menu_name
        FROM branch_mst bm
        INNER JOIN user_role_map urm ON urm.branch_id = bm.branch_id
        INNER JOIN role_menu_map rmm ON rmm.role_id = urm.role_id
        INNER JOIN menu_mst mm ON mm.menu_id = rmm.menu_id
        WHERE mm.menu_parent_id IS NOT NULL
          AND mm.active = 1
          AND bm.active = 1
        ORDER BY bm.branch_id, mm.menu_id;
    """
    query = text(sql)
    return query

def get_users_approval_portal(menu_id: int = None, branch_id: int = None):
    sql = f"select distinct(urm.user_id), um.email_id from user_role_map urm left join user_mst um on urm.user_id = um.user_id where urm.branch_id =:branch_id and urm.role_id in (select rmm.role_id from role_menu_map rmm where rmm.menu_id =:menu_id )  ;"
    query = text(sql)
    return query

def get_max_approval(menu_id: int = None):
    sql = f"SELECT max(approval_level) as max_approval FROM approval_mst where menu_id = :menu_id;"
    query = text(sql)
    return query

def get_approval_data(menu_id: int = None, branch_id: int = None):
    sql = f"SELECT approval_level, user_id, max_amount_single , day_max_amount , month_max_amount FROM approval_mst where menu_id = :menu_id and branch_id = :branch_id;"
    query = text(sql)
    return query

def get_portal_user_menus(user_id: int = None):
    sql = """
        select  urm.co_id ,cm.co_name , urm.branch_id,bm.branch_name ,  urm.role_id, rmm.menu_id, 
        mm.menu_name, mm.menu_path, mm.menu_parent_id  , 
        case when ccm.access_type =1 then 1 else rmm.access_type_id end as "access_type_id" 
        from user_role_map urm
        left join co_mst cm on cm.co_id= urm.co_id
        left join branch_mst bm on bm.branch_id = urm.branch_id
        left join role_menu_map rmm on rmm.role_id = urm.role_id
        left join menu_mst mm on mm.menu_id = rmm.menu_id and mm.active =1
        left join control_co_module ccm on urm.co_id = ccm.co_id and ccm.module_id = mm.module_mst_id
    where urm.user_id = :user_id and ifnull(ccm.access_type,0) not in (2) ;
    """
    query = text(sql)
    print(f"Constructed SQL for get_portal_user_menus: {query} == {user_id}")
    return query




# {
#     "detail": "Error fetching user edit setup data: (sqlalchemy.exc.InvalidRequestError) "
#     "A value is required for bind parameter 'user_id'\n[SQL: SELECT user_role_map_id, user_id, "
#     "role_id, co_id, branch_id FROM user_role_map WHERE user_id = %(user_id)s]\n[parameters: "
#     "[{}]]\n(Background on this error at: https://sqlalche.me/e/20/cd3x)"
# }