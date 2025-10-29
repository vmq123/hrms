import frappe
from frappe import _
from datetime import datetime, timedelta
from frappe.utils import now

from hrms.controllers.nl_generate_overtime_timesheets import generate_overtime_timesheets

from pypika import Criterion

from hrms.controllers.mk_process_attendance_for_an_employee import process_attendance
from hrms.controllers.mk_generate_overtime_timesheets_for_an_employee import generate_overtime_timesheets

frappe.utils.logger.set_log_level("INFO")
logger = frappe.logger("mk_logger")

def prepare_payroll_data_for_employee(employee_dn, start_date,end_date):
    job_id = f"prepare_payroll_data_for_employee-{employee_dn}-{start_date}-{end_date}"
    
    if frappe.db.exists("MK BG Job Status", job_id):
        msg = f"Job {job_id} has already been run, skipping..."
        logger.info(msg)
        doc = frappe.get_doc({"doctype": "MK BG Job Log","job_id" : job_id, "time": now(), "message": msg, "status": "NOT STARTED"})
        doc.insert(ignore_permissions=True)
        return

    doc = frappe.get_doc({"doctype": "MK BG Job Status","job_id" : job_id, "time": now(), "message": "Job started", "status": "STARTED"})
    doc.insert(ignore_permissions=True)
    
    process_attendance_after = start_date
    last_sync_of_checkin = end_date + " 23:59:00"

    publish_from_mk_employee_checkin(employee_dn, start_date,end_date)
    process_attendance(employee_dn, process_attendance_after,last_sync_of_checkin)
    generate_overtime_timesheets(employee_dn, start_date,end_date)
    frappe.get_doc({"doctype": "MK BG Job Log","job_id" : job_id, "time": now(), "message": "Job finished", "status": "FINISHED"}).insert(ignore_permissions=True)
    # doc = frappe.get_doc({"doctype": "MK BG Job Status","name" : job_id})
    doc.time = now()
    doc.status = "FINISHED"
    doc.save(ignore_permissions=True)

def publish_from_mk_employee_checkin(employee_dn, start_date,end_date):

    process_attendance_after = start_date
    last_sync_of_checkin = end_date + " 23:59:00"
    logs = frappe.get_all(
        "HRPlus Employee Checkin",
        fields=[
            "name",
            "employee",
            "log_type",
            "time",
            "latitude",
            "longitude",
            # "shift",
            # "shift_start",
            # "shift_end",
            # "shift_actual_start",
            # "shift_actual_end",
            "device_id",
        ],
        filters={
            "employee": employee_dn,
            # "skip_auto_attendance": 0,
            # "attendance": ("is", "not set"),
            # "time": (">=", process_attendance_after),
            # "time": ("<=", last_sync_of_checkin),
            # "shift_actual_end": ("<", self.last_sync_of_checkin),
            "time": ("between", [process_attendance_after, last_sync_of_checkin]),
            # "shift": self.name,
            # "offshift": 0,
        },
        order_by="employee,time",
    )
    logger.info(f"logs: {len(logs)}")
    cnt = 0
    for log in logs:
        try:
            frappe.get_doc(
                {
                    "doctype": "Employee Checkin",
                    "employee": log.employee,
                    "log_type": log.log_type,
                    "time": log.time,
                    "latitude": log.latitude,
                    "longitude": log.longitude,
                }
            ).insert(ignore_permissions=True,ignore_if_duplicate=True)
            cnt += 1
        except Exception as e:
            logger.error(f"Unexpected exception occurred: {e}")
    logger.info(f"Rows inserted: {cnt}")

def validate_days_having_only_one_checkin(start_date,end_date):
    process_attendance_after = start_date
    last_sync_of_checkin = end_date + " 23:59:00"

    days = get_days_having_only_one_checkin(process_attendance_after,last_sync_of_checkin)
    if days:
        frappe.throw('Tồn tại nhân viên chỉ có một lần checkin trong một ngày. Vui lòng bổ sung')
    # frappe.msgprint("validate_days_having_only_one_checkin passed")    

def get_days_having_only_one_checkin(start_timestamp, end_timestamp):
	values = {'start_ts': start_timestamp, 'end_ts': end_timestamp}
	data = frappe.db.sql("""
		select b.employee, b.checkin_date, count(b.time) count_checkin_logs from (
			select CAST(time AS DATE) AS checkin_date, employee, time from `tabHRPlus Employee Checkin` a
			where time between %(start_ts)s and %(end_ts)s
		) b
		group by b.employee, b.checkin_date
		having count(b.time) = 1
	""", values=values, as_dict=0)
	logger.info(f"data: {data}")
	return data