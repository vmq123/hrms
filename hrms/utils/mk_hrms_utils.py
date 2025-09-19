import frappe
from frappe import _

from frappe.query_builder import Criterion
from frappe.utils import add_days, cint, cstr, get_link_to_form, get_time, getdate, now_datetime, get_datetime

from datetime import datetime, timedelta# from shift_assignment, no change

def get_assigned_shifts_for_date(employee: str, for_timestamp: datetime) -> list[dict[str, str]]:
	"""Returns list of shifts with details for given date"""
	for_date = for_timestamp.date()
	prev_day = add_days(for_date, -1)
	next_day = add_days(for_date, 1)

	assignment = frappe.qb.DocType("Shift Assignment")
	return (
		frappe.qb.from_(assignment)
		.select(assignment.name, assignment.shift_type, assignment.start_date, assignment.end_date)
		.where(
			(assignment.employee == employee)
			& (assignment.docstatus == 1)
			& (assignment.status == "Active")
			# for shifts that exceed a day in duration or margins
			# eg: shift = 00:30:00 - 10:00:00, including margins (1 hr) = 23:30:00 - 11:00:00
			# if for_timestamp = 23:30:00 (falls in before shift margin), also fetch next days shift to find the correct shift
			& (assignment.start_date <= next_day)
			& (
				Criterion.any(
					[
						assignment.end_date.isnull(),
						(
							assignment.end_date.isnotnull()
							# for shifts that exceed a day in duration or margins
							# eg: shift = 15:00 - 23:30, including margins (1 hr) = 14:00 - 00:30
							# if for_timestamp = 00:30:00 (falls in after shift margin), also fetch prev days shift to find the correct shift
							& (prev_day <= assignment.end_date)
						),
					]
				)
			)
		)
	).run(as_dict=True)
# copy from shift_assignment, no change
def get_assigned_shift_details(shift_type_name: str, for_timestamp: datetime | None = None) -> dict:
	"""Returns a Dict containing shift details with the following data:
	'shift_type' - Object of DocType Shift Type,
	'start_datetime' - datetime of shift start on given timestamp,
	'end_datetime' - datetime of shift end on given timestamp,
	'actual_start' - datetime of shift start after adding 'begin_check_in_before_shift_start_time',
	'actual_end' - datetime of shift end after adding 'allow_check_out_after_shift_end_time' (None is returned if this is zero)

	:param shift_type_name (str): shift type name for which shift_details are required.
	:param for_timestamp (datetime, optional): Datetime value of checkin, if not provided considers current datetime
	"""
	if not shift_type_name:
		return frappe._dict()

	if for_timestamp is None:
		for_timestamp = now_datetime()

	shift_type = get_shift_type(shift_type_name)
	start_datetime, end_datetime = get_shift_timings(shift_type, for_timestamp)

	actual_start = start_datetime - timedelta(minutes=shift_type.begin_check_in_before_shift_start_time)
	actual_end = end_datetime + timedelta(minutes=shift_type.allow_check_out_after_shift_end_time)

	return frappe._dict(
		{
			"shift_type": shift_type,
			"start_datetime": start_datetime,
			"end_datetime": end_datetime,
			"actual_start": actual_start,
			"actual_end": actual_end,
		}
	)
# from shift_assignment, no change 
def get_shift_type(shift_type_name: str) -> dict:
	return frappe.get_cached_value(
		"Shift Type",
		shift_type_name,
		[
			"name",
			"start_time",
			"end_time",
			"begin_check_in_before_shift_start_time",
			"allow_check_out_after_shift_end_time",
		],
		as_dict=1,
	)
# from shift_assignment, no change
def get_shift_timings(shift_type: dict, for_timestamp: datetime) -> tuple:
	start_time = shift_type.start_time
	end_time = shift_type.end_time

	shift_actual_start = get_time(
		datetime.combine(for_timestamp, datetime.min.time())
		+ start_time
		- timedelta(minutes=shift_type.begin_check_in_before_shift_start_time)
	)
	shift_actual_end = get_time(
		datetime.combine(for_timestamp, datetime.min.time())
		+ end_time
		+ timedelta(minutes=shift_type.allow_check_out_after_shift_end_time)
	)
	for_time = get_time(for_timestamp.time())
	start_datetime = end_datetime = None

	if start_time > end_time:
		# shift spans across 2 different days
		if for_time >= shift_actual_start:
			# if for_timestamp is greater than start time, it's within the first day
			start_datetime = datetime.combine(for_timestamp, datetime.min.time()) + start_time
			for_timestamp += timedelta(days=1)
			end_datetime = datetime.combine(for_timestamp, datetime.min.time()) + end_time

		elif for_time < shift_actual_start:
			# if for_timestamp is less than start time, it's within the second day
			end_datetime = datetime.combine(for_timestamp, datetime.min.time()) + end_time
			for_timestamp += timedelta(days=-1)
			start_datetime = datetime.combine(for_timestamp, datetime.min.time()) + start_time
	elif (
		shift_actual_start > shift_actual_end
		and for_time < shift_actual_start
		and get_time(end_time) > shift_actual_end
	):
		# for_timestamp falls within the margin period in the second day (after midnight)
		# so shift started and ended on the previous day
		for_timestamp += timedelta(days=-1)
		end_datetime = datetime.combine(for_timestamp, datetime.min.time()) + end_time
		start_datetime = datetime.combine(for_timestamp, datetime.min.time()) + start_time
	elif (
		shift_actual_start > shift_actual_end
		and for_time > shift_actual_end
		and get_time(start_time) < shift_actual_start
	):
		# for_timestamp falls within the margin period in the first day (before midnight)
		# so shift started and ended on the next day
		for_timestamp += timedelta(days=1)
		start_datetime = datetime.combine(for_timestamp, datetime.min.time()) + start_time
		end_datetime = datetime.combine(for_timestamp, datetime.min.time()) + end_time
	else:
		# start and end timings fall on the same day
		start_datetime = datetime.combine(for_timestamp, datetime.min.time()) + start_time
		end_datetime = datetime.combine(for_timestamp, datetime.min.time()) + end_time

	return start_datetime, end_datetime
