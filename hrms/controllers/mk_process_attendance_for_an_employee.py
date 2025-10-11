from datetime import datetime
from itertools import groupby

import frappe
from frappe import _

from frappe.utils import cint


from hrms.hr.doctype.employee_checkin.employee_checkin import (
	mark_attendance_and_link_log,
)

EMPLOYEE_CHUNK_SIZE = 50

frappe.utils.logger.set_log_level("INFO")
logger = frappe.logger("mk_logger")

def process_attendance(employee_dn, process_attendance_after,last_sync_of_checkin):
    # shift_list = frappe.get_all("Shift Type", filters={"enable_auto_attendance": "1"}, pluck="name")
    # TODO: handle multiple shift assignment at the same time scenario
    shift_list = frappe.get_all("Shift Assignment", filters={"docstatus": "1", "employee":employee_dn}, pluck="shift_type")
    for shift_type_dn in shift_list:
        process_attendance_by_shift_type(shift_type_dn, employee_dn, process_attendance_after,last_sync_of_checkin)

def process_attendance_by_shift_type(shift_type_dn, employee_dn, process_attendance_after,last_sync_of_checkin):
    format_string_1 = "%Y-%m-%d %H:%M:%S"
    format_string_2 = "%Y-%m-%d"

    shift_type_doc = frappe.get_doc("Shift Type", shift_type_dn)
    
    shift_type_doc.process_attendance_after = datetime.strptime(process_attendance_after, format_string_2)
    shift_type_doc.last_sync_of_checkin = datetime.strptime(last_sync_of_checkin,format_string_1)
    shift_type_doc.save(
        ignore_permissions=True, # ignore write permissions during insert
        ignore_version=True # do not create a version record
    )
    logger.info(f"mk_process_attendance_for_an_employee.process_attendance.start : shift_type: {shift_type_doc}, employee: {employee_dn}")
    if (
        not cint(shift_type_doc.enable_auto_attendance)
        or not shift_type_doc.process_attendance_after
        or not shift_type_doc.last_sync_of_checkin
    ):
        return

    logs = get_employee_checkins(shift_type_dn,employee_dn,shift_type_doc.process_attendance_after,shift_type_doc.last_sync_of_checkin)
    group_key = lambda x: (x["employee"], x["shift_start"])  # noqa
    for key, group in groupby(sorted(logs, key=group_key), key=group_key):
        single_shift_logs = list(group)
        attendance_date = key[1].date()
        employee = key[0]

        if not shift_type_doc.should_mark_attendance(employee, attendance_date):
            continue

        (
            attendance_status,
            working_hours,
            late_entry,
            early_exit,
            in_time,
            out_time,
        ) = shift_type_doc.get_attendance(single_shift_logs)
        logger.info(f"mk_process_attendance_for_an_employee.process_attendance : attendance_date: {attendance_date}, attendance_status: {attendance_status}, working_hours: {working_hours}")
        mark_attendance_and_link_log(
            single_shift_logs,
            attendance_status,
            attendance_date,
            working_hours,
            late_entry,
            early_exit,
            in_time,
            out_time,
            shift_type_dn,
        )

    # commit after processing checkin logs to avoid losing progress
    frappe.db.commit()  # nosemgrep

    # assigned_employees = self.get_assigned_employees(self.process_attendance_after, True)
    # # mark absent in batches & commit to avoid losing progress since this tries to process remaining attendance
    # # right from "Process Attendance After" to "Last Sync of Checkin"
    # for batch in create_batch(assigned_employees, EMPLOYEE_CHUNK_SIZE):
    #     for employee in batch:
    #         self.mark_absent_for_dates_with_no_attendance(employee)
    #         self.mark_absent_for_half_day_dates(employee)

    #     frappe.db.commit()  # nosemgrep
    shift_type_doc.mark_absent_for_dates_with_no_attendance(employee_dn)
    shift_type_doc.mark_absent_for_half_day_dates(employee_dn)
    frappe.db.commit()
    logger.info(f"mk_process_attendance_for_an_employee.process_attendance.end : shift_type: {shift_type_doc}, employee: {employee_dn}")


def get_employee_checkins(shift_type_dn,employee_dn,process_attendance_after,last_sync_of_checkin) -> list[dict]:
    return frappe.get_all(
        "Employee Checkin",
        fields=[
            "name",
            "employee",
            "log_type",
            "time",
            "shift",
            "shift_start",
            "shift_end",
            "shift_actual_start",
            "shift_actual_end",
            "device_id",
        ],
        filters={
            "employee": employee_dn,
            "skip_auto_attendance": 0,
            "attendance": ("is", "not set"),
            "time": (">=", process_attendance_after),
            "shift_actual_end": ("<", last_sync_of_checkin),
            "shift": shift_type_dn,
            "offshift": 0,
        },
        order_by="employee,time",
    )