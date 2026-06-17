import logging
from fastapi import FastAPI, Request
from src.common.routers import router as common_router
from src.authorization.routers import common_router as auth_router
from src.common.companydata import router as company_router
from src.common.companyAdmin.menu import router as co_console_router
from src.common.companyAdmin.roles import router as co_roles_router
from src.common.companyAdmin.users import router as co_users_router
from src.common.portal.roles import router as co_portal_router
from src.common.portal.users import router as co_portal_users_router
from src.common.portal.menu import router as co_portal_menu_router
from src.common.portal.approval import router as co_portal_approval_router
from src.common.ctrldskAdmin.roles import router as co_ctrldsk_router
from src.common.ctrldskAdmin.users import router as co_ctrldsk_users_router
from src.common.ctrldskAdmin.orgs import router as co_ctrldsk_orgs_router
from src.common.companyAdmin.company import router as co_company_router
from src.common.ctrldskAdmin.menuportal import router as co_ctrldsk_menu_router
from src.common.companyAdmin.branch import router as co_branch_router
from src.common.companyAdmin.dept_subdept import router as co_dept_subdept_router

from src.masters.departments import router as dept_router
from src.masters.mechineMaster import router as machine_router
from src.masters.projectMaster import router as project_router 
from src.procurement.indent import router as indent_router
from src.procurement.po import router as po_router
from src.procurement.inward import router as inward_router
from src.procurement.material_inspection import router as material_inspection_router
from src.procurement.sr import router as sr_router
from src.procurement.drcr_note import router as drcr_note_router
from src.procurement.billpass import router as billpass_router
from src.procurement.reports import router as procurement_reports_router
from src.masters.party import router as party_router
from src.inventory.issue import router as issue_router
from src.inventory.reports import router as inventory_reports_router

from src.masters.items import router as item_router
from src.masters.warehouse import router as warehouse_router
from src.masters.castFactor import router as costFactor_router
from src.masters.juteQuality import router as jute_quality_router
from src.masters.juteSupplier import router as jute_supplier_router
from src.masters.juteSupplierMap import router as jute_supplier_map_router
from src.masters.juteMukamMaster import router as jute_mukam_router
from src.masters.yarnQuality import router as yarn_quality_router
from src.masters.machineSpgDetails import router as machine_spg_details_router
from src.masters.spinningQuality import router as spinning_quality_router
from src.masters.trolly import router as trolly_router
from src.masters.yarnTypeMaster import router as yarn_type_router
from src.masters.yarnMaster import router as yarn_master_router
from src.masters.batchPlanMaster import router as batch_plan_master_router
from src.masters.designation import router as designation_router
from src.masters.category import router as category_router
from src.masters.contractor import router as contractor_router
from src.masters.shift import router as shift_router
from src.masters.spell import router as spell_router
from src.masters.machineType import router as machine_type_router
from src.juteProcurement.jutePO import router as jute_po_router
from src.juteProcurement.juteGateEntry import router as jute_gate_entry_router
from src.juteProcurement.materialInspection import router as jute_material_inspection_router
from src.juteProcurement.mr import router as jute_mr_router
from src.juteProcurement.juteMukamRecv import router as jute_mukam_recvd_router
from src.juteProcurement.juteAgentMap import router as jute_agent_map_router
from src.juteProcurement.billPass import router as jute_bill_pass_router
from src.juteProcurement.issue import router as jute_issue_router
from src.juteProcurement.batchDailyAssign import router as batch_daily_assign_router
from src.juteProcurement.reports import router as jute_reports_router
from src.juteProduction.reports import router as spreader_reports_router
from src.juteProduction.drawingReports import router as drawing_reports_router
from src.juteProduction.spinningReports import router as spinning_reports_router
from src.juteProduction.spinningEmpBrkReports import router as spinning_emp_brk_reports_router
from src.juteProduction.windingReports import router as winding_reports_router
from src.juteProduction.otherReports import router as other_reports_router
from src.juteProduction.balesReports import router as bales_reports_router
from src.juteSQC.morrahWeight import router as morrah_wt_router
from src.sales.quotation import router as quotation_router
from src.sales.salesOrder import router as sales_order_router
from src.sales.deliveryOrder import router as delivery_order_router
from src.sales.salesInvoice import router as sales_invoice_router
from src.hrms.employee import router as hrms_employee_router
from src.hrms.payScheme import router as hrms_pay_scheme_router
from src.hrms.payParam import router as hrms_pay_param_router
from src.hrms.payRegister import router as hrms_pay_register_router
from src.hrms.payComponent import router as hrms_pay_component_router
from src.hrms.leaveType import router as hrms_leave_type_router
from src.hrms.empRateEntry import router as hrms_emp_rate_entry_router
from src.hrms.bioAttUpdation import router as hrms_bio_att_router
from src.hrms.dailyMachineEntry import router as hrms_daily_machine_router
from src.hrms.manMachine import router as hrms_man_machine_router
from src.hrms.desigNormsSet import router as hrms_desig_norms_router
from src.hrms.manMachineMst import router as hrms_man_machine_mst_router
from src.hrms.empAttendanceReport import router as hrms_emp_attendance_report_router
from src.hrms.empWagesReport import router as hrms_emp_wages_report_router
from src.production.mcStoppage import router as production_mc_stoppage_router
from src.misEntries.yarnPurchase import router as mis_entries_yarn_purchase_router
from src.misEntries.electricityDG import router as mis_entries_electricity_dg_router
from src.misReports.misReport import router as mis_reports_router
from src.config.cors import add_cors_middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
# from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Vowerp3b API")

# ✅ Add this to trust NGINX proxy headers (like X-Forwarded-Proto)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Add CORS middleware
add_cors_middleware(app)

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        print(f"Global API Error: {e}")
        return JSONResponse(status_code=500, content={"error": "Internal Server Error"})

print ('mama')
app.include_router(common_router, prefix="/api/common", tags=["Common"])
app.include_router(auth_router, prefix="/api/authRoutes", tags=["Auth"])
app.include_router(company_router, prefix="/api/companyRoutes", tags=["company"])
app.include_router(co_console_router, prefix="/api/companyAdmin", tags=["company-admin-menu"])
app.include_router(co_roles_router, prefix="/api/companyAdmin", tags=["company-admin-roles"])
app.include_router(co_users_router, prefix="/api/companyAdmin", tags=["company-admin-users"])
app.include_router(co_portal_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_users_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_menu_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_approval_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_ctrldsk_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-roles"])
app.include_router(co_ctrldsk_users_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-users"])
app.include_router(co_ctrldsk_orgs_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-orgs"])
app.include_router(co_company_router, prefix="/api/companyAdmin", tags=["company-admin-company"])
app.include_router(co_ctrldsk_menu_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-menu"])
app.include_router(co_branch_router, prefix="/api/companyAdmin", tags=["company-admin-branch"])
app.include_router(co_dept_subdept_router, prefix="/api/companyAdmin", tags=["company-admin-dept-subdept"])
app.include_router(item_router, prefix="/api/itemMaster", tags=["masters-items"])

app.include_router(dept_router, prefix="/api/deptMaster", tags=["masters-departments"])
app.include_router(machine_router, prefix="/api/mechMaster", tags=["masters-machines"])
app.include_router(project_router, prefix="/api/projectMaster", tags=["masters-projects"])

app.include_router(party_router, prefix="/api/partyMaster", tags=["masters-party"])
app.include_router(warehouse_router, prefix="/api/warehouseMaster", tags=["masters-warehouse"])
app.include_router(costFactor_router, prefix="/api/costFactorMaster", tags=["masters-costFactor"])
app.include_router(jute_quality_router, prefix="/api/juteQualityMaster", tags=["masters-jute-quality"])
app.include_router(jute_supplier_router, prefix="/api/juteSupplierMaster", tags=["masters-jute-supplier"])
app.include_router(jute_supplier_map_router, prefix="/api/juteSupplierMap", tags=["masters-jute-supplier-map"])
app.include_router(jute_mukam_router, prefix="/api/juteMukamMaster", tags=["masters-jute-mukam"])
app.include_router(yarn_quality_router, prefix="/api/yarnQualityMaster", tags=["masters-yarn-quality"])
app.include_router(machine_spg_details_router, prefix="/api/machineSpgDetailsMaster", tags=["masters-machine-spg-details"])
app.include_router(spinning_quality_router, prefix="/api/spinningQualityMaster", tags=["masters-spinning-quality"])
app.include_router(trolly_router, prefix="/api/trollyMaster", tags=["masters-trolly"])

app.include_router(yarn_type_router, prefix="/api/yarnTypeMaster", tags=["masters-yarn-type"])
app.include_router(yarn_master_router, prefix="/api/yarnMaster", tags=["masters-yarn"])
app.include_router(batch_plan_master_router, prefix="/api/batchPlanMaster", tags=["masters-batch-plan"])
app.include_router(designation_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(category_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(contractor_router, prefix="/api/contractorMaster", tags=["masters-contractor"])
app.include_router(shift_router, prefix="/api/masters", tags=["masters-shift"])
app.include_router(spell_router, prefix="/api/masters", tags=["masters-spell"])
app.include_router(machine_type_router, prefix="/api/machineTypeMaster", tags=["masters-machine-type"])

app.include_router(indent_router, prefix="/api/procurementIndent", tags=["procurement-indent"])
app.include_router(po_router, prefix="/api/procurementPO", tags=["procurement-po"])
app.include_router(inward_router, prefix="/api/procurementInward", tags=["procurement-inward"])
app.include_router(material_inspection_router, prefix="/api/materialInspection", tags=["procurement-material-inspection"])
app.include_router(sr_router, prefix="/api/storesReceipt", tags=["procurement-stores-receipt"])
app.include_router(drcr_note_router, prefix="/api/drcrNote", tags=["procurement-drcr-note"])
app.include_router(billpass_router, prefix="/api/billPass", tags=["procurement-bill-pass"])
app.include_router(procurement_reports_router, prefix="/api/procurementReports", tags=["procurement-reports"])

# Jute Procurement routers
app.include_router(jute_po_router, prefix="/api/jutePO", tags=["jute-procurement-po"])
app.include_router(jute_gate_entry_router, prefix="/api/juteGateEntry", tags=["jute-procurement-gate-entry"])
app.include_router(jute_material_inspection_router, prefix="/api/juteMaterialInspection", tags=["jute-procurement-material-inspection"])
app.include_router(jute_mr_router, prefix="/api/juteMR", tags=["jute-procurement-mr"])
app.include_router(jute_mukam_recvd_router, prefix="/api/juteMukamRecv", tags=["jute-procurement-mukam-recvd"])
app.include_router(jute_agent_map_router, prefix="/api/juteAgentMap", tags=["jute-procurement-agent-map"])
app.include_router(jute_bill_pass_router, prefix="/api/juteBillPass", tags=["jute-procurement-bill-pass"])
app.include_router(jute_issue_router, prefix="/api/juteIssue", tags=["jute-procurement-issue"])
app.include_router(batch_daily_assign_router, prefix="/api/batchDailyAssign", tags=["jute-procurement-batch-daily-assign"])
app.include_router(jute_reports_router, prefix="/api/juteReports", tags=["jute-procurement-reports"])
app.include_router(spreader_reports_router, prefix="/api/spreaderReports", tags=["jute-production-spreader-reports"])
app.include_router(drawing_reports_router, prefix="/api/drawingReports", tags=["jute-production-drawing-reports"])
app.include_router(spinning_reports_router, prefix="/api/spinningReports", tags=["jute-production-spinning-reports"])
app.include_router(spinning_emp_brk_reports_router, prefix="/api/spinningEmpBrkReports", tags=["jute-production-spinning-emp-brk-reports"])
app.include_router(winding_reports_router, prefix="/api/windingReports", tags=["jute-production-winding-reports"])
app.include_router(other_reports_router, prefix="/api/otherReports", tags=["jute-production-other-reports"])
app.include_router(bales_reports_router, prefix="/api/balesReports", tags=["jute-production-bales-reports"])

# Jute SQC routers
app.include_router(morrah_wt_router, prefix="/api/juteSQC", tags=["jute-sqc-morrah-weight"])

# Inventory routers
app.include_router(issue_router, prefix="/api/inventoryIssue", tags=["inventory-issue"])
app.include_router(inventory_reports_router, prefix="/api/inventoryReports", tags=["inventory-reports"])

# Sales routers
app.include_router(quotation_router, prefix="/api/salesQuotation", tags=["sales-quotation"])
app.include_router(sales_order_router, prefix="/api/salesOrder", tags=["sales-order"])
app.include_router(delivery_order_router, prefix="/api/salesDeliveryOrder", tags=["sales-delivery-order"])
app.include_router(sales_invoice_router, prefix="/api/salesInvoice", tags=["sales-invoice"])

# HRMS routers
app.include_router(hrms_employee_router, prefix="/api/hrms", tags=["hrms-employee"])
app.include_router(hrms_pay_scheme_router, prefix="/api/hrms", tags=["hrms-pay-scheme"])
app.include_router(hrms_pay_param_router, prefix="/api/hrms", tags=["hrms-pay-param"])
app.include_router(hrms_pay_register_router, prefix="/api/hrms", tags=["hrms-pay-register"])
app.include_router(hrms_pay_component_router, prefix="/api/hrms", tags=["hrms-pay-component"])
app.include_router(hrms_leave_type_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_emp_rate_entry_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_bio_att_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_daily_machine_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_man_machine_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_desig_norms_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_man_machine_mst_router, prefix="/api/hrmsMasters", tags=["hrms-masters"])
app.include_router(hrms_emp_attendance_report_router, prefix="/api/hrmsReports", tags=["hrms-reports"])
app.include_router(hrms_emp_wages_report_router, prefix="/api/hrmsReports", tags=["hrms-reports"])
app.include_router(production_mc_stoppage_router, prefix="/api/productionEntry", tags=["production-entry"])
app.include_router(mis_entries_yarn_purchase_router, prefix="/api/misEntries", tags=["mis-entries"])
app.include_router(mis_entries_electricity_dg_router, prefix="/api/misEntries", tags=["mis-entries"])
app.include_router(mis_reports_router, prefix="/api/misReports", tags=["mis-reports"])


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    logger.info("Application is starting up...")
    # Automated hourly bio-attendance pipeline (no-op unless BIO_ATT_AUTO_ENABLED).
    try:
        from src.hrms.bio_att_auto_pipeline import start_scheduler
        start_scheduler()
    except Exception:
        logger.exception("Failed to start bio_att_auto scheduler")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application is shutting down...")
    try:
        from src.hrms.bio_att_auto_pipeline import stop_scheduler
        stop_scheduler()
    except Exception:
        logger.exception("Failed to stop bio_att_auto scheduler")

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # 👇 Startup logic
#     logger.info("Application is starting up...")
#     yield
#     # 👇 Shutdown logic
#     logger.info("Application is shutting down...")

# app = FastAPI(lifespan=lifespan)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
