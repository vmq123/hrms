import frappe
from hrms.controllers.nl_get_employee_attendance import get_employee_attendance, get_employee_overtime_attendance
from pypika import Criterion

frappe.utils.logger.set_log_level("INFO")
logger = frappe.logger("mk_logger")

# this is MK Payroll added
# TODO: get real duration from shift_type instead of 8
def add_attendance_data_to_salary_slip(salary_slip,overtime_15,overtime_20):
	logger.info(f"payroll_entry.add_attendance_data_to_salary_slip.start")
	# salary_slip = salary_slip_doc
	maximum_monthly_hours = salary_slip.payment_days * 8
	logger.info(f"maximum_monthly_hours: {maximum_monthly_hours}")
	salary_slip.attendance = []
	salary_slip.regular_overtime = []
	salary_slip.holiday_overtime = []

	salary_slip.regular_working_hours = 0
	salary_slip.overtime_hours = 0
	salary_slip.holiday_hours = 0

	attendance = get_employee_attendance(salary_slip.get('employee'), salary_slip.get('start_date'), salary_slip.get('end_date'))
	# print(f"attendance: {attendance}")
	overtime_attendance = get_employee_overtime_attendance(salary_slip.get('employee'), salary_slip.get('start_date'), salary_slip.get('end_date'))
	# print(f"overtime_attendance: {overtime_attendance}")
	# holiday_dates = get_holiday_dates(salary_slip.get('employee'))
	holiday_dates = salary_slip.get_holidays_for_employee(salary_slip.start_date,salary_slip.end_date)
	# print(f"holiday_dates: {holiday_dates}")


	if attendance:
		for attendance_entry in attendance:
			logger.info(f"attendance_entry: {attendance_entry}")
			if attendance_entry.get('attendance_date') not in (holiday_dates or []) and attendance_entry.get('working_hours') > 0:
				billiable_hours = 0

				if not attendance_entry.get('include_unpaid_breaks'):
					billiable_hours = attendance_entry.get('payment_hours')
				else:
					if attendance_entry.get('working_hours') > attendance_entry.get('min_hours_to_include_a_break'):
						billiable_hours = attendance_entry.get('working_hours') - (attendance_entry.get('unpaid_breaks_minutes') / 60)
					else:
						billiable_hours = attendance_entry.get('working_hours')

				salary_slip.append('attendance', {
					'attendance_date': attendance_entry.get('attendance_date'),
					'hours_worked': attendance_entry.get('working_hours'),
					'include_unpaid_breaks': attendance_entry.get('include_unpaid_breaks'),
					'unpaid_breaks_minutes': attendance_entry.get('unpaid_breaks_minutes'),
					'min_hours_to_include_a_break': attendance_entry.get('min_hours_to_include_a_break'),
					'billiable_hours': billiable_hours
				})

				salary_slip.regular_working_hours += billiable_hours


	if overtime_attendance:
		for overtime_attendance_record in overtime_attendance:
			logger.info(f"overtime_attendance_record: {overtime_attendance_record}")
			if overtime_attendance_record.get('activity_type') == overtime_15:
				salary_slip.append('regular_overtime', {
					'timesheet': overtime_attendance_record.get('name'),
					'hours': overtime_attendance_record.get('total_hours')
				})
				salary_slip.overtime_hours += overtime_attendance_record.get('total_hours')

			if overtime_attendance_record.get('activity_type') == overtime_20:
				salary_slip.append('holiday_overtime', {
					'timesheet': overtime_attendance_record.get('name'),
					'hours': overtime_attendance_record.get('total_hours')
				})
				salary_slip.holiday_hours += overtime_attendance_record.get('total_hours')

	if salary_slip.regular_working_hours > maximum_monthly_hours:
		# salary_slip.overtime_hours += salary_slip.regular_working_hours - maximum_monthly_hours
		salary_slip.regular_working_hours = maximum_monthly_hours
	elif salary_slip.regular_working_hours < maximum_monthly_hours:
		balance_to_maximum_monthly_hours = maximum_monthly_hours - salary_slip.regular_working_hours
		if salary_slip.overtime_hours <= balance_to_maximum_monthly_hours:
			salary_slip.regular_working_hours += salary_slip.overtime_hours
			salary_slip.overtime_hours = 0
		else:
			salary_slip.overtime_hours -= balance_to_maximum_monthly_hours
			salary_slip.regular_working_hours += balance_to_maximum_monthly_hours


def add_incentive_data_to_salary_slip(salary_slip):
	logger.info(f"payroll_entry.add_incentive_data_to_salary_slip.start: salary_slip.employee,start_date,end_date: {salary_slip.employee} {salary_slip.start_date} {salary_slip.end_date}")
	start_date, end_date=salary_slip.start_date, salary_slip.end_date

	sales_team = frappe.qb.DocType("Sales Team")
	sales_order = frappe.qb.DocType("Sales Order")
	sales_person = frappe.qb.DocType("Sales Person")
	# salary_slip_qb = frappe.qb.DocType("Salary Slip")

	conditions = [sales_order.docstatus == 1, sales_order.transaction_date[start_date:end_date],
				# salary_slip_qb.incentive_based_salary == 1, salary_slip_qb.name == salary_slip.name,
				sales_person.employee ==  salary_slip.employee,
				sales_team.parenttype == "Sales Order"]

	query = frappe.qb.from_(sales_team) \
		.left_join(sales_order) \
		.on(sales_team.parent == sales_order.name) \
		.left_join(sales_person) \
		.on(sales_team.sales_person == sales_person.name) \
		.select(
		sales_team.parent.as_("parent"),
		sales_team.allocated_percentage.as_("allocated_percentage"),
		sales_team.allocated_amount.as_("allocated_amount"),
		sales_team.commission_rate.as_("commission_rate"),
		sales_team.incentives.as_("incentives")
	).where(Criterion.all(conditions))

	incentive_records = query.run(as_dict=True)
	incentives_total = 0

	for entry in incentive_records:
		logger.info(f"entry: {entry}")
		salary_slip.append('incentive', {
			'sales_order': entry.get('parent'),
			'allocated_percentage': entry.get('allocated_percentage'),
			'allocated_amount': entry.get('allocated_amount'),
			'commission_rate': entry.get('commission_rate'),
			'incentives': entry.get('incentives')
		})
		incentives_total += entry.incentives
	logger.info(f"add_incentive_data_to_salary_slip: incentives_total: {incentives_total}")
	salary_slip.incentives_total = incentives_total
	
def calculate_component_in_salary_slip(salary_slip):
	emp = frappe.get_doc("Employee",salary_slip.employee)
	if emp.employment_type == 'HDDH':
		calculate_component_in_salary_slip_HDDH(salary_slip,emp)
	elif emp.employment_type == 'HDTV':
		calculate_component_in_salary_slip_HDDH(salary_slip,emp)
	else:
		calculate_component_in_salary_slip_HDDH(salary_slip,emp)

def calculate_component_in_salary_slip_HDDH(salary_slip,emp):
	emp = frappe.get_doc("Employee",salary_slip.employee)
	if emp.employment_type == 'HDKV':
		pdr = 1
	else:
		pdr = salary_slip.payment_days/salary_slip.total_working_days
	c6 = append_component(salary_slip,"Lương cơ bản","6","",emp.custom_luong_co_ban)
	c7 = append_component(salary_slip,"Phụ cấp chức vụ","7","",emp.custom_phu_cap_chuc_vu)
	c8 = append_component(salary_slip,"Phụ cấp trách nhiệm","8","",emp.custom_phu_cap_trach_nhiem)
	ckdbh = c6+c7+c8
	c9 = append_component(salary_slip,"Ăn ca","9","",emp.custom_an_ca)
	c10 = append_component(salary_slip,"Điện thoại","10","",emp.custom_dien_thoai)
	c11 = append_component(salary_slip,"Xăng xe","11","",emp.custom_xang_xe)
	c12 = append_component(salary_slip,"Hỗ trợ nhà ở","12","",emp.custom_ho_tro_nha_o)
	c13 = append_component(salary_slip,"Phụ cấp khác","13","",emp.custom_phu_cap_khac)
	# c14 = append_component(salary_slip,"Tổng cộng LCB + các khoản PC","14","6+7+8+9+10 +11+12+13",c6+c7+c8+c9+c10+c11+c12+c13)
	c14 = c6+c7+c8+c9+c10+c11+c12+c13
	c16 = append_component(salary_slip,"Tiền lương theo ngày công","16","",c14*pdr)
	c18 = 0
	c19 = 0
	c20 = append_component(salary_slip,"Tổng thu nhập","20","",c16+c18+c19)
	c21 = ckdbh * 0.175
	c22 = ckdbh * 0.03
	c23 = ckdbh * 0.01
	c24 = append_component(salary_slip,"BHXH","24","",max(0,ckdbh*0.08))
	c25 = append_component(salary_slip,"BHYT","25","",max(0,ckdbh*0.015))
	c26 = append_component(salary_slip,"BHTN","26","",max(0,ckdbh*0.01))
	c27 = append_component(salary_slip,"Tổng BH","27","",c24+c25+c26)
	c32 = min(730000,c9*pdr)
	c38 = c20-c32
	c39 = 11000000
	c41 = 4400000 * emp.custom_so_luong_npt_duoc_bhxh_cho_phep_gtgc
	c46 = append_component(salary_slip,"Thu nhập tính thuế","46","",max(0,c38-(c39+c41)-c27))
	if c46<=5000000:
		c48 = c46 * 0.05
	elif c46<=10000000:
		c48 = c46 * 0.1 - 250000
	elif c46<=18000000:
		c48 = c46 * 0.15 - 750000
	elif c46<=32000000:
		c48 = c46 * 0.2 - 1650000
	elif c46<=52000000:
		c48 = c46 * 0.25 - 3250000
	elif c46<=80000000:
		c48 = c46 * 0.3 - 5850000
	else:
		c48 = c46 * 0.35 - 9850000
	c28 = append_component(salary_slip,"Thuế TNCN phải nộp","48","",c48)
	c29 = append_component(salary_slip,"Lương thực lĩnh trong tháng","29","20-27-28",c20-c27-c28)

	salary_slip.custom_gross_pay_component = c20
	salary_slip.custom_thue_tncn = c28
	salary_slip.custom_bhxh_ctd = c21
	salary_slip.custom_bhyt_ctd = c22
	salary_slip.custom_bhtn_ctd = c23	
	salary_slip.custom_bhxh = c24
	salary_slip.custom_bhyt = c25
	salary_slip.custom_bhtn = c26	

def append_component(salary_slip,name1,id,formular,amount):
	# comp = frappe.new_doc({"doctype":"Hrplus Salary Component","name1":name1,"id":id,"formular":formular,"amount":amount})
	comp = frappe.new_doc("Hrplus Salary Component")
	comp.name1=name1
	comp.id=id
	comp.formular=formular
	comp.amount=amount
	salary_slip.append('custom_salary_component',comp)
	logger.info(f"append_component: {salary_slip}: {name1}-{id}-{formular}-{amount}")
	return comp.amount