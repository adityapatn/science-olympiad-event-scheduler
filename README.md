# 2026 Division C Science Olympiad Event Scheduler

What this program does:
- Reads student tryouts, events, and rules data from a CSV file or in-line variables.
- Uses a backtracking solver (with heuristics) to assign events to students while respecting blocks, per-student limits, tryout performance, and simple rules.
- Prints per-student assignments to the console.
- Writes the event assignment to a time-stamped csv file in the project directory.

Preparing Data:
1. Using a CSV File
   - Open example.csv to see the required format (Students / Events / Rules / Similar Events).
   - Make a copy (e.g., `data.csv`) and edit the Student rows and the Event rows to match your local tryouts and event counts.
   - Edit the source_path variable to your file name.
   - Rules and similar-groups are optional; leave blank sections if you don't need them.
2. Using in-line variables:
   - Set each variable as shown in event.py

How to run:
1. In `event.py` set the data source at the top of the main section:
   - To use the CSV file: set `data_source = "your_file_name.csv"`.
   - To use the inline definition in the script: set `data_source = "user"`.
2. From the project directory run `python3 event.py`.
3. Copy the output from the console or CSV file!

Notes and tips:
- Use `example.csv` as a template. The CSV sections are:
  - Students: one row per student with event+rank pairs
  - Event,Number of Students,Block,Type: one event per row with the student count, block (use "No Conflict" for events that do not conflict with others), and event type.
  - Configurable Rules: optional Mandatory and Banned subsections that the scheduler will follow (keep students apart, lock in an assignment).
  - Similar Events: groups of related events that the scheduler uses as last-priority for event assignment.

Original project created by Aditya Patnaik 2025