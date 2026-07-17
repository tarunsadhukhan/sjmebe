# Database Tables Used in vowerp3be

**Database:** MySQL (SQLAlchemy + PyMySQL), multi-tenant:

| Database | Purpose |
|----------|---------|
| `vowconsole3` | Console DB — orgs, console users/roles/menus, org-module mapping (shared across tenants) |
| `<tenant>` (e.g. `sjm`, `sls`) | Tenant DB — all business data; selected per request from the `subdomain` |

Connection is configured in `env/database.env` (`DATABASE_HOST`, `DATABASE_DEFAULT=vowconsole3`); current dev server `187.127.187.26:3306`.

**Source column:** `model` = SQLAlchemy model in `src/models/`, `raw SQL` = referenced only in raw `text()` queries.

Generated 2026-07-15 by cross-referencing code references against the live `sjm` schema (223 tenant tables/views + 9 console tables in use).

---

## Console DB (`vowconsole3`)

| Table | Source |
|-------|--------|
| con_menu_master | raw SQL |
| con_module_masters | raw SQL |
| con_org_master | model |
| con_org_module_mapping | raw SQL |
| con_role_master | model |
| con_role_menu_map | raw SQL |
| con_status_master | raw SQL |
| con_user_master | model |
| con_user_role_mapping | model |

## Tenant DB — Auth, Users, Menus

| Table | Source |
|-------|--------|
| user_mst | model |
| user_role_map | model |
| roles_mst | model |
| roles | raw SQL |
| role_menu_map | model |
| role_app_menu_map | raw SQL |
| menu_mst | model |
| menus | raw SQL |
| menu_type_mst | model |
| module_mst | model |
| approval_mst | model |
| status_mst | model |
| co_mst | model |
| co_config | model |
| control_co_module | raw SQL |

## Organization & Common Masters

| Table | Source |
|-------|--------|
| branch_mst | model |
| dept_mst | model |
| sub_dept_mst | model |
| designation_mst | model |
| designation_norms_mst | raw SQL |
| contractor_mst | model |
| project_mst | model |
| country_mst | model |
| state_mst | model |
| city_mst | raw SQL |
| currency_mst | model |
| entity_type_mst | model |
| expense_type_mst | model |
| category_mst | model |
| cost_factor_mst | model |
| cost_element_mst | raw SQL |
| additional_charges_mst | model |
| bank_details_mst | raw SQL |
| tax_mst | model |
| tax_type_mst | model |
| tds_mst | model |
| uom_mst | model |
| uom_item_map_mst | model |
| shift_mst | model |
| spell_mst | model |
| warehouse_mst | model |
| trolly_mst | model |
| fne_master | raw SQL |

## Party

| Table | Source |
|-------|--------|
| party_mst | model |
| party_branch_mst | model |
| party_type_mst | model |

## Items & BOM

| Table | Source |
|-------|--------|
| item_mst | model |
| item_grp_mst | model |
| item_make | model |
| item_minmax_mst | model |
| item_type_master | model |
| item_bom | model |
| item_bom_hdr_mst | raw SQL |
| bom_cost_entry | raw SQL |
| bom_cost_snapshot | raw SQL |

## Machines

| Table | Source |
|-------|--------|
| machine_mst | model |
| machine_type_mst | model |
| mechine_code_master | raw SQL |
| mechine_spg_details | model |
| mc_occu_link_mst | raw SQL |

## Procurement

| Table | Source |
|-------|--------|
| proc_enquiry | model |
| proc_enquiry_dtl | model |
| proc_price_enquiry_response | model |
| proc_price_enquiry_response_dtl | model |
| proc_indent | model |
| proc_indent_dtl | model |
| proc_indent_dtl_cancel | model |
| proc_po | model |
| proc_po_dtl | model |
| proc_po_dtl_cancel | model |
| proc_po_additional | model |
| po_gst | model |
| proc_gst | model |
| proc_tds | model |
| proc_inward | model |
| proc_inward_dtl | model |
| proc_inward_additional | model |
| proc_transfer | model |
| proc_transfer_dtl | model |

## Inventory

| Table | Source |
|-------|--------|
| issue_hdr | model |
| issue_li | model |

## Jute Procurement

| Table | Source |
|-------|--------|
| jute_supplier_mst | model |
| jute_supp_party_map | model |
| jute_agent_map | model |
| jute_mukam_mst | model |
| jute_quality_mst | model |
| jute_yarn_mst | model |
| jute_yarn_type_mst | model |
| jute_lorry_mst | model |
| jute_po | model |
| jute_po_li | model |
| jute_mr | model |
| jute_mr_li | model |
| jute_issue | model |
| jute_issue_primary | model |
| jute_moisture_rdg | model |
| jute_mukam_recvd | raw SQL |
| jute_sqc_morrah_wt | model |

## Jute Production

| Table | Source |
|-------|--------|
| assorting_entry | model |
| tbl_jute_received | model |
| jute_batch_plan | model |
| jute_batch_plan_li | model |
| jute_batch_daily_assign | model |
| tbl_daily_drawing | raw SQL |
| tbl_daily_sperder | model |
| tbl_daily_finishing | raw SQL |
| tbl_daily_bales_transaction | raw SQL |
| tbl_daily_vvfd_transaction | raw SQL |
| tbl_daily_summ_mechine_data | raw SQL |
| tbl_yarn_transaction | raw SQL |
| tbl_mc_stoppage | raw SQL |
| tbl_other_entries | raw SQL |
| tbl_offday_mst | raw SQL |
| daily_doff_tbl | raw SQL |
| daily_doff_frames_winding | raw SQL |
| spinning_quality_mst | model |
| spinning_type_mst | raw SQL |
| sprd_jute_quality_mst | raw SQL |
| winding_quality_master | model |
| yarn_quality_master | model |
| std_rate_card | raw SQL |

## Sales

| Table | Source |
|-------|--------|
| sales_quotation | model |
| sales_quotation_dtl | model |
| sales_quotation_dtl_gst | model |
| sales_order | model |
| sales_order_dtl | model |
| sales_order_dtl_gst | model |
| sales_order_dtl_hessian | model |
| sales_order_govtskg | raw SQL |
| sales_order_govtskg_dtl | raw SQL |
| sales_delivery_order | model |
| sales_delivery_order_dtl | model |
| sales_delivery_order_dtl_gst | model |
| sales_invoice | model |
| sales_invoice_dtl | model |
| sales_invoice_dtl_gst | model |
| sale_invoice_jute | raw SQL |
| invoice_type_mst | model |
| invoice_type_co_map | model |

## Accounting

| Table | Source |
|-------|--------|
| acc_account_determination | model |
| acc_bill_ref | model |
| acc_bill_settlement | model |
| acc_financial_year | model |
| acc_ledger | model |
| acc_ledger_group | model |
| acc_opening_bill | model |
| acc_period_lock | model |
| acc_voucher | model |
| acc_voucher_line | model |
| acc_voucher_gst | model |
| acc_voucher_type | model |
| acc_voucher_numbering | model |
| acc_voucher_approval_log | model |
| acc_voucher_warning | model |
| drcr_note | model |
| drcr_note_dtl | model |
| drcr_note_dtl_gst | model |

## HRMS & Bio-Attendance

| Table | Source |
|-------|--------|
| hrms_blood_group | model |
| hrms_ed_address_details | model |
| hrms_ed_bank_details | model |
| hrms_ed_contact_details | model |
| hrms_ed_esi | model |
| hrms_ed_official_details | model |
| hrms_ed_personal_details | model |
| hrms_ed_pf | model |
| hrms_ed_resign_details | model |
| hrms_employee_face | model |
| hrms_experience_details | model |
| hrms_leave_types_mst | model |
| bio_attendance_table | raw SQL |
| temp_bio_attendance_table | raw SQL |
| bio_att_jobs | raw SQL |
| tbl_master_bio_link_mst | raw SQL |
| daily_attendance | raw SQL |
| daily_attendance_basic | raw SQL |
| daily_attendance_process_table | raw SQL |
| daily_ebmc_attendance | raw SQL |
| employee_rate_table | raw SQL |
| temp_employee_rate_table | raw SQL |

## Payroll

| Table | Source |
|-------|--------|
| pay_cm_job_payment_links | model |
| pay_company_components | model |
| pay_components | model |
| pay_components_custom | model |
| pay_custemp_components_custom | model |
| pay_customer_employee_payroll | model |
| pay_customer_employee_payscheme | model |
| pay_customer_employee_period | model |
| pay_customer_employee_structure | model |
| pay_employee_payperiod | model |
| pay_employee_payroll | model |
| pay_employee_payroll_status | model |
| pay_employee_payroll_status_log | model |
| pay_employee_payscheme | model |
| pay_employee_structure | model |
| pay_external_components | model |
| pay_generic | model |
| pay_holiday_wage_pay_register | model |
| pay_period | model |
| pay_period_status | model |
| pay_processed_payscheme | model |
| pay_register | model |
| pay_report | model |
| pay_report_combinations | model |
| pay_scheme | model |
| pay_scheme_details | model |
| pay_scheme_master | model |
| pay_scheme_parameter_category | model |
| pay_seq_payroll | model |
| pay_slip | model |
| pay_slip_components | model |
| pay_slip_parameters | model |
| pay_wages_mode | model |

## Views

| View | Source |
|------|--------|
| vw_approved_inward_qty | model |
| vw_hands_report | raw SQL |
| vw_hands_std_report | raw SQL |
| vw_item_balance_qty_by_branch | model |
| vw_item_balance_qty_by_branch_new | model |
| vw_item_with_group_path | raw SQL |
| vw_jute_stock_outstanding | model |
| vw_man_machine | raw SQL |
| vw_proc_indent_outstanding | model |
| vw_proc_indent_outstanding_new | model |
| vw_proc_po_outstanding_new | model |

---

## Known Gaps

Model tables defined in code but **missing from the live `sjm` DB**:

- `academic_years` (src/models/hrms.py)
- `daily_drawing_transaction` (src/models/jute.py)
- `mechine_master` (src/models/jute.py — note `mechine_code_master` exists instead)
