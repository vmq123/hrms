# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.naming import set_name_by_naming_series
from frappe.utils import add_years, cint, get_link_to_form, getdate

from erpnext.setup.doctype.employee.employee import Employee

class EmployeeMaster(Employee):
	def autoname(self):
		naming_method = frappe.db.get_value("HR Settings", None, "emp_created_by")
		if not naming_method:
			frappe.throw(_("Please setup Employee Naming System in Human Resource > HR Settings"))
		else:
			if naming_method == "Naming Series":
				set_name_by_naming_series(self)
			elif naming_method == "Employee Number":
				self.name = self.employee_number
			elif naming_method == "Full Name":
				self.set_employee_name()
				self.name = self.employee_name

		self.employee = self.name


def validate_onboarding_process(doc, method=None):
	"""Validates Employee Creation for linked Employee Onboarding"""
	if not doc.job_applicant:
		return

	employee_onboarding = frappe.get_all(
		"Employee Onboarding",
		filters={
			"job_applicant": doc.job_applicant,
			"docstatus": 1,
			"boarding_status": ("!=", "Completed"),
		},
	)
	if employee_onboarding:
		onboarding = frappe.get_doc("Employee Onboarding", employee_onboarding[0].name)
		onboarding.validate_employee_creation()
		onboarding.db_set("employee", doc.name)


def publish_update(doc, method=None):
	import hrms

	hrms.refetch_resource("hrms:employee", doc.user_id)

def before_insert_hook(doc, method=None):
	doc.user_id = None

def before_validate_hook(doc, method=None):
	update_status_for_user_and_sales_person(doc)

def after_insert_hook(doc, method=None):
	update_job_applicant_and_offer(doc, method)
	create_user(doc.name,user=None, email = doc.personal_email)
	# update_user_permission("Insert", doc.personal_email, "Employee", doc.name)
	update_user_permission("Insert", doc.personal_email, "Company", frappe.defaults.get_global_default("company"))
	if doc.custom_role_profile == 'HRPlus Employee':
		update_user_permission("Insert", doc.personal_email, "Employee", doc.name)
	else:
		update_user_permission("Delete", doc.personal_email, "Employee", doc.name)
	
	create_sales_person_if_having_commission(doc)

def on_update_hook(doc, method=None):
	update_approver_role(doc, method=None)
	publish_update(doc, method=None)
	update_role_profile(doc)
	create_sales_person_if_having_commission(doc)

def update_status_for_user_and_sales_person(doc):
	# user = frappe.get_doc("User",doc.user_id)
	# sp = frappe.get_doc("Sales Person",doc.name)
	if doc.status == 'Active':
		# user.update({"enabled":1})
		# sp.update({"enabled":1})
		if frappe.db.exists("User",doc.user_id):
			user = frappe.get_doc("User",doc.user_id)
			user.update({"enabled":1})
			user.save(ignore_permissions=True)
		# frappe.db.set_value("User",doc.user_id,"status","Active")
		# frappe.db.set_value("User",doc.user_id,"enabled",1)
		if frappe.db.exists("Sales Person",doc.name):
			frappe.db.set_value("Sales Person",doc.name,"enabled",1)
	else:
		# frappe.db.set_value("User",doc.user_id,"enabled",0)
		if frappe.db.exists("User",doc.user_id):
			user = frappe.get_doc("User",doc.user_id)
			user.update({"enabled":0})
			user.save(ignore_permissions=True)
		if frappe.db.exists("Sales Person",doc.name):
			frappe.db.set_value("Sales Person",doc.name,"enabled",0)
		# user.update({"enabled":0})
		# sp.update({"enabled":0})
	# user.save(ignore_permissions=True)
	# sp.save(ignore_permissions=True)
	frappe.db.commit() 


def update_role_profile(doc):
	user = frappe.get_doc("User",doc.user_id)
	if(user.role_profile_name != doc.custom_role_profile):
		user.role_profile_name = doc.custom_role_profile
		user.save(ignore_permissions=True)

		if doc.custom_role_profile == 'HRPlus Employee':
			update_user_permission("Insert", doc.user_id, "Employee", doc.name)
		else:
			update_user_permission("Delete", doc.user_id, "Employee", doc.name)
		

def update_user_permission(action , user_id, allow, for_value):
	logger = frappe.logger("mk_logger")
	frappe.utils.logger.set_log_level("INFO")
	args = {
		"user": user_id,
		"allow": allow,
		"for_value": for_value
	}
	try:
		# args = frappe._dict(args)
		if action == "Insert":
			logger.info(f"update_user_permission, prepare step 1 to Insert {args}")
			if not frappe.db.exists("User Permission",args):
				logger.debug(f"update_user_permission, prepare step 2 to Insert...")
				doc = frappe.new_doc("User Permission")
				doc.update(args)
				doc.insert(ignore_permissions=True)
				logger.info(f"update_user_permission, done step 3 to Insert")
		if action == "Delete":
			logger.info(f"update_user_permission, prepare step 1 to Delete {args}")
			if frappe.db.exists("User Permission", args):
				logger.debug(f"update_user_permission, prepare step 2 to Delete...")
				frappe.db.delete("User Permission",args)
				logger.info(f"update_user_permission, done step 3 to Delete")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), 'update_user_permission failed')

def create_sales_person_if_having_commission(employee):
	if employee.custom_has_commission_from_sales:
		if frappe.db.exists("Sales Person", {"sales_person_name": employee.first_name}):
			return
		sp = frappe.new_doc("Sales Person")
		sp.sales_person_name = employee.first_name
		sp.parent_sales_person = 'Sales Team'
		sp.employee = employee.name
		sp.commission_rate = 10
		sp.insert(ignore_permissions=True)

def create_user(employee, user=None, email=None):
	emp = frappe.get_doc("Employee", employee)

	employee_name = emp.employee_name.split(" ")
	middle_name = last_name = ""

	if len(employee_name) >= 3:
		last_name = " ".join(employee_name[2:])
		middle_name = employee_name[1]
	elif len(employee_name) == 2:
		last_name = employee_name[1]

	first_name = employee_name[0]

	if email:
		emp.prefered_email = email

	user = frappe.new_doc("User")
	user.update(
		{
			"name": emp.employee_name,
			"full_name": emp.employee_name,
			"email": emp.personal_email,
			"username": email,
			"enabled": 1,
			"send_welcome_email": 0,
			"first_name": first_name,
			"middle_name": middle_name,
			"last_name": last_name,
			"gender": emp.gender,
			"birth_date": emp.date_of_birth,
			"mobile_no": emp.cell_number,
			# "bio": emp.bio,
			"role_profile_name": emp.custom_role_profile,
			"module_profile": emp.custom_role_profile
		}
	)
	user.insert(ignore_permissions=True)
	emp.user_id = user.name
	emp.save(ignore_permissions=True)
	return user.name

def update_job_applicant_and_offer(doc, method=None):
	"""Updates Job Applicant and Job Offer status as 'Accepted' and submits them"""
	if not doc.job_applicant:
		return

	applicant_status_before_change = frappe.db.get_value("Job Applicant", doc.job_applicant, "status")
	if applicant_status_before_change != "Accepted":
		frappe.db.set_value("Job Applicant", doc.job_applicant, "status", "Accepted")
		frappe.msgprint(
			_("Updated the status of linked Job Applicant {0} to {1}").format(
				get_link_to_form("Job Applicant", doc.job_applicant), frappe.bold(_("Accepted"))
			)
		)
	offer_status_before_change = frappe.db.get_value(
		"Job Offer", {"job_applicant": doc.job_applicant, "docstatus": ["!=", 2]}, "status"
	)
	if offer_status_before_change and offer_status_before_change != "Accepted":
		job_offer = frappe.get_last_doc("Job Offer", filters={"job_applicant": doc.job_applicant})
		job_offer.status = "Accepted"
		job_offer.flags.ignore_mandatory = True
		job_offer.flags.ignore_permissions = True
		job_offer.save()

		msg = _("Updated the status of Job Offer {0} for the linked Job Applicant {1} to {2}").format(
			get_link_to_form("Job Offer", job_offer.name),
			frappe.bold(doc.job_applicant),
			frappe.bold(_("Accepted")),
		)
		if job_offer.docstatus == 0:
			msg += "<br>" + _("You may add additional details, if any, and submit the offer.")

		frappe.msgprint(msg)


def update_approver_role(doc, method=None):
	"""Adds relevant approver role for the user linked to Employee"""
	if doc.leave_approver:
		user = frappe.get_doc("User", doc.leave_approver)
		user.flags.ignore_permissions = True
		user.add_roles("Leave Approver")

	if doc.expense_approver:
		user = frappe.get_doc("User", doc.expense_approver)
		user.flags.ignore_permissions = True
		user.add_roles("Expense Approver")


def update_employee_transfer(doc, method=None):
	"""Unsets Employee ID in Employee Transfer if doc is deleted"""
	if frappe.db.exists("Employee Transfer", {"new_employee_id": doc.name, "docstatus": 1}):
		emp_transfer = frappe.get_doc("Employee Transfer", {"new_employee_id": doc.name, "docstatus": 1})
		emp_transfer.db_set("new_employee_id", "")


@frappe.whitelist()
def get_timeline_data(doctype, name):
	"""Return timeline for attendance"""
	from frappe.desk.notifications import get_open_count

	out = {}

	open_count = get_open_count(doctype, name)
	out["count"] = open_count["count"]

	timeline_data = dict(
		frappe.db.sql(
			"""
			select unix_timestamp(attendance_date), count(*)
			from `tabAttendance` where employee=%s
			and attendance_date > date_sub(curdate(), interval 1 year)
			and status in ('Present', 'Half Day')
			group by attendance_date""",
			name,
		)
	)

	out["timeline_data"] = timeline_data
	return out


@frappe.whitelist()
def get_retirement_date(date_of_birth=None):
	if date_of_birth:
		try:
			retirement_age = cint(frappe.db.get_single_value("HR Settings", "retirement_age") or 60)
			dt = add_years(getdate(date_of_birth), retirement_age)
			return dt.strftime("%Y-%m-%d")
		except ValueError:
			# invalid date
			return
