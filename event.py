from collections import defaultdict
from typing import Dict, List, Optional
from datetime import datetime
import math
import os
import csv

MAX_EVENTS_PER_STUDENT = 4
MAX_BUILDS_PER_STUDENT = 2

def build_event_to_block(blocks: Dict[str, List[str]]) -> Dict[str, str]:
    mapping = {}
    for block_name, evs in blocks.items():
        for e in evs:
            mapping[e] = block_name
    return mapping

def eligible(student: str, event: str, student_assignments: Dict[str, List[str]],
             event_slots_remaining: Dict[str, int], event_to_block: Dict[str, str],
             rules: Dict, max_per_student: int) -> bool:
    # slot available
    if event_slots_remaining.get(event, 0) <= 0:
        return False

    # not already assigned
    if event in student_assignments.get(student, []):
        return False

    # per-student limit
    if len(student_assignments.get(student, [])) >= max_per_student:
        return False

    # banned student-event pairs (rules structure: rules['banned']['student-event'] = [(student, event), ...])
    for (s, e) in rules.get('banned', {}).get('student-event', []):
        if s == student and e == event:
            return False

    # banned student-student pairs (rules['banned']['student-student'] = [(studentA, studentB), ...])
    # prevent assigning `student` to `event` if a banned peer is already assigned to that same event
    banned_pairs = rules.get('banned', {}).get('student-student', [])
    if banned_pairs:
        assigned_students_for_event = {s for s, evs in student_assignments.items() if event in evs}
        for a, b in banned_pairs:
            if student == a and b in assigned_students_for_event:
                return False
            if student == b and a in assigned_students_for_event:
                return False

    # block conflict
    block = event_to_block.get(event)
    for assigned_event in student_assignments.get(student, []):
        if event_to_block.get(assigned_event) == block:
            return False

    current_build_count = sum(1 for ae in student_assignments.get(student, []) if ae in build_events)
    if event in build_events and current_build_count >= MAX_BUILDS_PER_STUDENT:
        return False

    return True

def find_assignment(students: List[str], events: List[str], preferences: Dict[str, List[str]],
                    blocks: Dict[str, List[str]], event_student_requirements: Dict[str, int],
                    rules: Dict, performance: Dict[str, List[str]] = None,
                    max_per_student: int = MAX_EVENTS_PER_STUDENT) -> Optional[Dict[str, List[str]]]:
    # prepare structures
    event_to_block = build_event_to_block(blocks)
    # build a map event -> group name from similar_groups (if defined)
    event_to_group = {}
    try:
        for gname, evs in similar_groups.items():
            for ev in evs:
                event_to_group[ev] = gname
    except NameError:
        event_to_group = {}

    # create list of slots (event repeated required times)
    slots = []
    for e, cnt in event_student_requirements.items():
        for _ in range(cnt):
            slots.append(e)

    # heuristic: sort events by fewer candidate students (we will recompute during search)

    student_assignments: Dict[str, List[str]] = {s: [] for s in students}
    event_slots_remaining = dict(event_student_requirements)

    # enforce mandatory student-event pairings from rules (if any)
    for (mand_student, mand_event) in rules.get('mandatory', {}).get('student-event', []):
        # student and event must exist
        if mand_student not in student_assignments:
            return None
        if mand_event not in event_slots_remaining:
            return None
        # check eligibility under current state (slot availability, block conflicts, per-student limits, cannot rules, build limits)
        if not eligible(mand_student, mand_event, student_assignments, event_slots_remaining, event_to_block, rules, max_per_student):
            return None
        # perform assignment and consume one slot
        student_assignments[mand_student].append(mand_event)
        event_slots_remaining[mand_event] -= 1
        # remove one occurrence of the event from slots (must exist)
        try:
            slots.remove(mand_event)
        except ValueError:
            return None

    # helper to compute eligible students for a slot, ordered by preference, event performance, and current load
    def candidates_for(event: str) -> List[str]:
        cand = [s for s in students if eligible(s, event, student_assignments, event_slots_remaining, event_to_block, rules, max_per_student)]
        # sort by preference rank (lower index = higher preference), then by current load
        def pref_key(s):
            # preference ranking (lower index = higher preference)
            prefs = preferences.get(s, [])
            try:
                pref_rank = prefs.index(event)
            except ValueError:
                pref_rank = 999

            # performance ranking for this event: lower index = better performer
            perf_rank = 999
            if performance:
                perf_list = performance.get(event, [])
                try:
                    perf_rank = perf_list.index(s)
                except ValueError:
                    perf_rank = 999

            # group match: prefer students who already have an assigned event in this event's group
            group = event_to_group.get(event)
            if group:
                has_group = any(event_to_group.get(ae) == group for ae in student_assignments.get(s, []))
                group_penalty = 0 if has_group else 1
            else:
                group_penalty = 1

            # Order: performance first (highest priority), then preference, then group match, then current load
            return (pref_rank, perf_rank, group_penalty, len(student_assignments.get(s, [])))

        cand.sort(key=pref_key)
        return cand

    # utility to check pair_together feasibility: if event has a partner and student isn't already assigned to partner,
    # ensure partner has at least one slot and student eligible for partner as well (ignoring partner-slot-consumption for now)
    pair_map = defaultdict(list)
    for a, b in rules.get('pair_together', []):
        pair_map[a].append(b)
        pair_map[b].append(a)

    def pair_feasible(student: str, event: str) -> bool:
        for partner in pair_map.get(event, []):
            # if already assigned to partner, fine
            if partner in student_assignments.get(student, []):
                continue
            # else check room for partner
            if event_slots_remaining.get(partner, 0) <= 0:
                return False
            # and student must be eligible for partner (except slot count which we'll consume later)
            # perform a light eligibility check: block and cannot and per-student limit
            # create a shallow copy of assignments to check block conflict
            if not eligible(student, partner, student_assignments, event_slots_remaining, event_to_block, rules, max_per_student):
                return False
        return True

    # backtracking over slots using MRV heuristic
    def backtrack(remaining_slots: List[str]) -> bool:
        if not remaining_slots:
            return True

        # MRV: pick the slot (event) with fewest candidates now
        best_event = None
        best_candidates = None
        best_idx = 0
        best_key = None
        for idx, ev in enumerate(remaining_slots):
            cands = candidates_for(ev)
            # if any event has zero candidates, prune immediately
            if not cands:
                return False
            # prioritize events where exactly one student tried out (performance list length == 1)
            single_tryout = 0 if (performance and len(performance.get(ev, [])) == 1) else 1
            key = (single_tryout, len(cands))
            if best_key is None or key < best_key:
                best_key = key
                best_candidates = cands
                best_event = ev
                best_idx = idx

        event = best_event
        # try candidates in order
        for student in best_candidates:
            if not pair_feasible(student, event):
                continue

            # place
            student_assignments[student].append(event)
            event_slots_remaining[event] -= 1

            next_slots = remaining_slots[:best_idx] + remaining_slots[best_idx+1:]

            # if event had pair partners that student is not yet assigned to, try to reserve a partner now
            partners = [p for p in pair_map.get(event, []) if p not in student_assignments[student]]
            partners_assigned = []
            can_assign_partners = True
            for partner in partners:
                # find a candidate slot for partner in next_slots
                if partner not in next_slots:
                    can_assign_partners = False
                    break
                # check if student can take partner now
                if not eligible(student, partner, student_assignments, event_slots_remaining, event_to_block, rules, max_per_student):
                    can_assign_partners = False
                    break
                # assign partner tentatively: consume one occurrence from next_slots and from slots remaining
                # remove first occurrence
                next_slots.remove(partner)
                student_assignments[student].append(partner)
                event_slots_remaining[partner] -= 1
                partners_assigned.append(partner)

            if can_assign_partners and backtrack(next_slots):
                return True

            # undo partner assignments
            for p in partners_assigned:
                student_assignments[student].remove(p)
                event_slots_remaining[p] += 1
            # undo placement
            student_assignments[student].remove(event)
            event_slots_remaining[event] += 1

        return False

    ok = backtrack(slots)
    if ok:
        return student_assignments
    else:
        return None

def pretty_print(assignments: Dict[str, List[str]]):
    # Column-formatted output. Events for each student are printed in the order of their preferences.

    # determine how many event columns to show
    max_assigned = max((len(evs) for evs in assignments.values()), default=0)
    # header columns: Student, Event 1..N
    num_cols = max_assigned

    # build per-student ordered lists according to preferences
    ordered_assignments: Dict[str, List[str]] = {}
    for student, evs in assignments.items():
        prefs = preferences.get(student, [])
        # sort assigned events by preference order (those not in prefs go last, in stable order)
        def pref_key(e):
            try:
                return prefs.index(e)
            except ValueError:
                return 999

        ordered = sorted(evs, key=pref_key)
        ordered_assignments[student] = ordered

    # compute column widths
    student_col_w = max(len(s) for s in ordered_assignments.keys())
    event_col_ws = []
    for i in range(num_cols):
        maxw = 8  # minimum
        for evs in ordered_assignments.values():
            if i < len(evs):
                maxw = max(maxw, len(evs[i]))
        event_col_ws.append(maxw)

    # print header
    header = f"{ 'Student'.ljust(student_col_w) }"
    for i, w in enumerate(event_col_ws, start=1):
        header += "  " + f"Event{i}".ljust(w)
    print("")
    print(header)
    print('-' * len(header))

    # print rows
    for student in sorted(ordered_assignments.keys()):
        row = student.ljust(student_col_w)
        evs = ordered_assignments[student]
        for i, w in enumerate(event_col_ws):
            val = evs[i] if i < len(evs) else ""
            row += "  " + val.ljust(w)
        print(row)

def csv_output(assignments: Dict[str, List[str]]):
	#Write assignments to time-stamped csv file

	out_path = os.path.join(os.path.dirname(__file__), "science_olympiad_event_scheduler_output_" + datetime.now().strftime("%H:%M:%S") + ".csv")
	# determine max events assigned to size the header
	max_assigned = max((len(evs) for evs in assignments.values()), default=0)
	fieldnames = ['Student'] + [f'Event{i+1}' for i in range(max_assigned)]

	with open(out_path, 'w', newline='', encoding='utf-8') as f:
		writer = csv.writer(f)
		writer.writerow(fieldnames)
		# rows: sorted student names for stable output
		for student in sorted(assignments.keys()):
			evs = assignments.get(student, [])
			# pad to max_assigned with empty strings
			row = [student] + evs + [''] * (max_assigned - len(evs))
			writer.writerow(row)
	# optional confirmation
	print(f"\nWrote assignments to {out_path}")

if __name__ == '__main__':
    #data to be specified
    data_path = "example.csv" #can be "user" or "file_name.csv"

    if data_path == "user":
        tryouts = {
            'Student1': [('Circuit Lab', 8), ('Quantum Quandaries', 2), ('Experimental Design', 12), ('Codebusters', 9)],
            'Student2': [('Anatomy and Physiology', 15), ('Forensics', 6)],
            'Student3': [('Boomilever', 1), ('Chemistry Lab', 13), ('Codebusters', 18)],
            'Student4': [('Designer Genes', 7), ('Material Science', 4), ('Chemistry Lab', 11)],
            'Student5': [('Rocks and Minerals', 5), ('Dynamic Planet', 14), ('Material Science', 6)],
            'Student6': [('Anatomy and Physiology', 3), ('Entomology', 20)],
            'Student7': [('Boomilever', 2), ('Forensics', 10), ('Quantum Quandaries', 16)],
            'Student8': [('Water Quality', 4), ('Entomology', 9), ('Designer Genes', 13)],
            'Student9': [('Astronomy', 1), ('Circuit Lab', 17)],
            'Student10': [('Electric Vehicle', 6), ('Sustainable Energy', 8), ('Anatomy and Physiology', 19)],
            'Student11': [('Quantum Quandaries', 11), ('Designer Genes', 5), ('Rocks and Minerals', 22)],
            'Student12': [('Boomilever', 9), ('Material Science', 14), ('Forensics', 12), ('Chemistry Lab', 16)],
            'Student13': [('Circuit Lab', 3), ('Astronomy', 20), ('Material Science', 18)],
            'Student14': [('Quantum Quandaries', 7), ('Astronomy', 10), ('Hovercraft', 25)],
            'Student15': [('Circuit Lab', 2), ('Water Quality', 15), ('Sustainable Energy', 6), ('Designer Genes', 21)],
        }

        no_conflict_events = [
            'Quantum Quandaries', 'Codebusters', 'Helicopter', 'Hovercraft',
            'Boomilever', 'Electric Vehicle', 'Sustainable Energy'
        ]

        build_events = no_conflict_events + ["Machines", "Sustainable Energy"]
        blocks = {
            'Block 1': ['Experimental Design', 'Entomology', 'Astronomy'],
            'Block 2': ['Forensics', 'Engineering CAD', 'Anatomy and Physiology'],
            'Block 3': ['Chemistry Lab', 'Machines'],
            'Block 4': ['Disease Detectives', 'Remote Sensing'],
            'Block 5': ['Rocks and Minerals', 'Material Science', 'Designer Genes'],
            'Block 6': ['Circuit Lab', 'Dynamic Planet', 'Water Quality'],
        }

        rules = {
            "mandatory": {
                "student-event": []  # list of (student, event) tuples
            },
            "banned": {
                "student-event": [],   # list of (student, event) tuples
                "student-student": []  # list of (studentA, studentB) tuples
            }
        }

        similar_groups = {
            'Group1': ['Rocks and Minerals', 'Dynamic Planet'],
            'Group2': ['Astronomy', 'Remote Sensing'],
            'Group3': ['Anatomy and Physiology', 'Disease Detectives', 'Designer Genes'],
            'Group4': ['Electric Vehicle', 'Sustainable Energy', 'Circuit Lab'],
            'Group5': ['Chemistry Lab', 'Forensics', 'Material Science'],
            'Group6': ['Engineering CAD'],
            'Group7': ['Codebusters'],
            'Group8': ['Water Quality', 'Entomology'],
            'Group9': ['Experimental Design'],
            'Group10': ['Helicopter', 'Hovercraft', 'Boomilever', 'Machines'],
            'Group11': ['Quantum Quandaries'],
        }
    else: #data needs to be collected from data.csv
        # if relative, resolve next to this script
        if not os.path.isabs(data_path):
            data_path = os.path.join(os.path.dirname(__file__), data_path)

        rows = []
        with open(data_path, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            for r in reader:
                # normalize row: strip each cell; keep empty strings for missing cols
                rows.append([c.strip() for c in r])

        n = len(rows)
        idx = 0

        # find Students header (first row whose first cell startswith 'Student' case-insensitive)
        while idx < n and (len(rows[idx]) == 0 or not rows[idx][0].lower().startswith('student')):
            idx += 1

        tryouts = {}
        no_conflict_events = []
        blocks = {}
        event_student_requirements = {}
        build_events = []
        rules = {"mandatory": {"student-event": []}, "banned": {"student-event": [], "student-student": []}}
        similar_groups = {}

        # parse student tryouts section
        if idx < n:
            # header row consumed
            idx += 1
            while idx < n:
                if len(rows[idx]) == 0 or (len(rows[idx]) > 0 and rows[idx][0] == ''):
                    idx += 1
                    continue
                # stop when we hit Event header
                if rows[idx][0].lower().startswith('event'):
                    break
                cols = rows[idx]
                name = cols[0]
                pairs = []
                # parse Event/Rank pairs from remaining columns (assume event, rank, event, rank, ...)
                j = 1
                while j + 1 < len(cols):
                    ev = cols[j].strip()
                    rk = cols[j + 1].strip()
                    if ev:
                        try:
                            rank = int(rk) if rk != '' else None
                        except ValueError:
                            rank = None
                        if rank is None:
                            # if no numeric rank, keep a high sentinel (so present but low priority)
                            pairs.append((ev, 999))
                        else:
                            pairs.append((ev, rank))
                    j += 2
                tryouts[name] = pairs
                idx += 1

        # parse events table
        while idx < n and not (len(rows[idx]) > 0 and rows[idx][0].lower().startswith('event')):
            idx += 1
        if idx < n and rows[idx][0].lower().startswith('event'):
            # skip header
            idx += 1
            while idx < n:
                if len(rows[idx]) == 0 or rows[idx][0] == '':
                    idx += 1
                    continue
                first = rows[idx][0].strip()
                # stop at Rules header (if present)
                if first.lower() == 'rules':
                    break
                cols = rows[idx]
                ev = cols[0].strip()
                num = 0
                blk = ''
                typ = ''
                if len(cols) > 1 and cols[1].strip() != '':
                    try:
                        num = int(cols[1].strip())
                    except ValueError:
                        num = 0
                if len(cols) > 2:
                    blk = cols[2].strip()
                # optional Type column (e.g. "Build", "Knowledge", etc.)
                if len(cols) > 3:
                    typ = cols[3].strip()
                event_student_requirements[ev] = num
                if blk.lower() == 'no conflict':
                    no_conflict_events.append(ev)
                else:
                    if blk == '':
                        # put into a default unnamed block if no block provided
                        blk = 'Block: Unspecified'
                    blocks.setdefault(blk, []).append(ev)
                # if the event type contains "build" (case-insensitive), record it as a build event
                if typ and 'build' in typ.lower():
                    build_events.append(ev)
                idx += 1

        # parse Rules section (if present)
        while idx < n and not (len(rows[idx]) > 0 and rows[idx][0].strip().lower() == 'rules'):
            idx += 1
        if idx < n and rows[idx][0].strip().lower() == 'rules':
            idx += 1
            # Expect subsections Mandatory, Banned, etc.
            while idx < n:
                if len(rows[idx]) == 0 or rows[idx][0] == '':
                    idx += 1
                    continue
                section = rows[idx][0].strip().lower()
                idx += 1
                if section == 'mandatory':
                    # skip possible header line 'Student,Event'
                    if idx < n and len(rows[idx]) > 0 and rows[idx][0].strip().lower() == 'student':
                        idx += 1
                    # read entries until blank line or next known section
                    while idx < n:
                        if len(rows[idx]) == 0 or rows[idx][0].strip() == '':
                            idx += 1
                            break
                        if rows[idx][0].strip().lower() in ('banned', 'similar events'):
                            break
                        cols = rows[idx]
                        if len(cols) > 1 and cols[0].strip() and cols[1].strip():
                            rules['mandatory']['student-event'].append((cols[0].strip(), cols[1].strip()))
                        idx += 1
                elif section == 'banned':
                    # parse two banned subsections: Student,Event and Student,Student
                    # skip possible header
                    # parse student-event banned
                    if idx < n and len(rows[idx]) > 0 and rows[idx][0].strip().lower() == 'student':
                        # could be header 'Student,Event'
                        idx += 1
                    # collect student-event bans until a blank line or a header that starts with 'student' and second col 'student'
                    while idx < n:
                        if len(rows[idx]) == 0 or rows[idx][0].strip() == '':
                            idx += 1
                            break
                        # detect start of student-student subsection
                        if len(rows[idx]) > 1 and rows[idx][0].strip().lower() == 'student' and rows[idx][1].strip().lower() == 'student':
                            idx += 1
                            break
                        cols = rows[idx]
                        if len(cols) > 1 and cols[0].strip() and cols[1].strip():
                            rules['banned']['student-event'].append((cols[0].strip(), cols[1].strip()))
                        idx += 1
                    # parse student-student bans (if present)
                    # skip header if still present
                    if idx < n and len(rows[idx]) > 1 and rows[idx][0].strip().lower() == 'student' and rows[idx][1].strip().lower() == 'student':
                        idx += 1
                    while idx < n:
                        if len(rows[idx]) == 0 or rows[idx][0].strip() == '':
                            idx += 1
                            break
                        # stop on Similar Events
                        if rows[idx][0].strip().lower() == 'similar events':
                            break
                        cols = rows[idx]
                        if len(cols) > 1 and cols[0].strip() and cols[1].strip():
                            rules['banned']['student-student'].append((cols[0].strip(), cols[1].strip()))
                        idx += 1
                else:
                    # unknown subsection: stop
                    break

        # parse Similar Events
        while idx < n and not (len(rows[idx]) > 0 and rows[idx][0].strip().lower() == 'similar events'):
            idx += 1
        if idx < n and rows[idx][0].strip().lower() == 'similar events':
            idx += 1
            group_idx = 1
            while idx < n:
                if len(rows[idx]) == 0:
                    idx += 1
                    continue
                # collect non-empty cells as group members
                members = [c for c in rows[idx] if c and c.strip()]
                members = [m.strip() for m in members]
                if members:
                    similar_groups[f'Group{group_idx}'] = members
                    group_idx += 1
                idx += 1

        # ensure variables exist for downstream code
        # (tryouts, no_conflict_events, blocks, event_student_requirements, rules, similar_groups are now set)

    #derived data
    # add a unique NoConflict block for each no-conflict event
    for ev in no_conflict_events:
        blocks[f'NoConflict: {ev}'] = [ev]

    # flatten events list
    events = [e for evs in blocks.values() for e in evs]

    # event requirements provided by the user
    event_student_requirements = {
        'Anatomy and Physiology': 2,
        'Astronomy': 2,
        'Boomilever': 2,
        'Chemistry Lab': 2,
        'Circuit Lab': 2,
        'Codebusters': 3,
        'Designer Genes': 2,
        'Disease Detectives': 2,
        'Dynamic Planet': 2,
        'Electric Vehicle': 2,
        'Engineering CAD': 2,
        'Entomology': 2,
        'Experimental Design': 3,
        'Forensics': 2,
        'Hovercraft': 2,
        'Helicopter': 2,
        'Machines': 2,
        'Material Science': 2,
        'Quantum Quandaries': 2,
        'Remote Sensing': 2,
        'Robot Tour': 2,
        'Rocks and Minerals': 2,
        'Sustainable Energy': 2,
        'Water Quality': 2,
    }

    # derive preferences: student -> [events ordered best->worst]
    preferences = {}
    for student, evs in tryouts.items():
        ordered = [e for e, r in sorted(evs, key=lambda x: x[1])]
        preferences[student] = ordered

    # derive performance: event -> [students ordered best->worst]
    perf_temp = {}
    for student, evs in tryouts.items():
        for event, rank in evs:
            perf_temp.setdefault(event, []).append((student, rank))
    performance = {}
    for event, entries in perf_temp.items():
        entries.sort(key=lambda x: x[1])
        performance[event] = [s for s, r in entries]

    # derive students list from tryouts
    students = list(tryouts.keys())
    total_slots = (sum(event_student_requirements.values()))
    minimum_events = math.ceil(total_slots / len(students))

    # Similar-event groupings (least-priority clustering). These groups are used as a final
    # tie-breaker after performance and preference: students who already have an event in the
    # same group are slightly preferred so related events cluster where possible.

    assignments = find_assignment(students, events, preferences, blocks, event_student_requirements, rules, performance)
    if assignments is None:
        print("Failed to find a complete assignment with given constraints.")
    else:
        pretty_print(assignments)
        csv_output(assignments)