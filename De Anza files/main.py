
import json
import os
import re
import difflib

INSTITUTION_MAP = {
    7: "UC, San Diego",
    11: "California Polytechnic University, San Luis Obispo",
    12: "CSU, Monterey Bay",
    21: "CSU, East Bay",
    24: "CSU, Stanislaus",
    29: "CSU, Fresno",
    39: "San Jose State University",
    42: "CSU, Northridge",
    46: "UC, Riverside",
    60: "CSU, Sacramento",
    75: "California Polytechnic University, Pomona",
    76: "CSU, Los Angeles",
    79: "UC, Berkeley",
    81: "CSU, Long Beach",
    88: "Sonoma State University",
    89: "UC, Davis",
    98: "CSU, Bakersfield",
    113: "De Anza College",
    116: "San Francisco State University",
    117: "UC, Los Angeles",
    128: "UC, Santa Barbara",
    129: "CSU, Fullerton",
    132: "UC, Santa Cruz",
    141: "CSU, Chico",
    143: "CSU, Channel Islands",
    144: "UC, Merced",
}

def norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in (" b s", " b a", " b m", " b f a", " b s c"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def score(query: str, target: str) -> float:
    return difflib.SequenceMatcher(None, query, target).ratio()


user_uni = input("Enter Full University Name to Transfer to: ").strip()

name_to_id = {v.lower(): k for k, v in INSTITUTION_MAP.items()}
uni_names = list(name_to_id.keys())
uni_matches = difflib.get_close_matches(user_uni.lower(), uni_names, n=3, cutoff=0.4)
if not uni_matches:
    raise ValueError("University not found in INSTITUTION_MAP.")

if user_uni.lower() not in uni_matches:
    print("\nTop university matches:")
    for i, name in enumerate(uni_matches, start=1):
        print(f"{i}. {INSTITUTION_MAP[name_to_id[name]]}")
    choice = input("Pick 1-3 (or press Enter for #1): ").strip()
    idx = 0 if choice == "" else max(1, min(3, int(choice))) - 1
    user_id = name_to_id[uni_matches[idx]]
    user_uni = INSTITUTION_MAP[user_id]
else:
    user_id = name_to_id[user_uni.lower()]

print(user_uni)
print("University ID: ", user_id)

script_dir = os.path.dirname(os.path.abspath(__file__))
candidate_dirs = [
    script_dir,
    os.path.join(script_dir, "de anza specific"),
]
base_dir = next((d for d in candidate_dirs if os.path.isdir(d)), script_dir)

folder = os.path.join(base_dir, f"113-{user_id}")
if not os.path.isdir(folder):
    raise FileNotFoundError(
        f"No folder found for 113-{user_id} under {base_dir}"
    )
user_major = input("Enter Major you want to transfer into: ").strip()

q = norm(user_major)
matches = []
for name in os.listdir(folder):
    if not name.endswith(".json"):
        continue
    path = os.path.join(folder, name)
    try: 
        with open(path, "r") as f:
            tmp = json.load(f)
    except Exception:
        continue
    major_name = tmp.get("major", "")
    s = score(q, norm(major_name))
    for token in q.split():
        if token and token in norm(major_name):
            s += 0.05
    matches.append((s, major_name, path))

matches.sort(reverse=True)
if not matches:
    raise FileNotFoundError("No majors found in that folder.")

print("\nTop matches:")
for i, (s, major_name, path) in enumerate(matches[:3], start=1):
    print(f"{i}. {major_name}  (score={s:.2f})")

choice = input("Pick 1-3 (or press Enter for #1): ").strip()
idx = 0 if choice == "" else max(1, min(3, int(choice))) - 1
target_path = matches[idx][2]

with open(target_path, "r") as f:
    data = json.load(f)

# Institution ID -> name map (from all De Anza specific JSONs)


def course_key(course: dict) -> tuple:
    return (
        course.get("prefix", ""),
        course.get("courseNumber", ""),
        course.get("courseTitle", ""),
    )


def fmt_course(course: dict) -> str:
    prefix = course.get("prefix", "")
    number = course.get("courseNumber", "")
    title = course.get("courseTitle", "")
    return f"{prefix} {number} — {title}".strip()


# Build mapping: target (UC) course -> list of De Anza courses
target_to_sources = {}
for ag in data.get("agreements", []) or []:
    target = ag.get("target", {}) or {}
    t_key = course_key(target)
    for course_group in ag.get("courses", []) or []:
        group_name = course_group.get("group", "")
        for c in course_group.get("classes", []) or []:
            target_to_sources.setdefault(t_key, []).append(
                {
                    "group": group_name,
                    "course": c,
                }
            )


print(f"MAJOR: {data.get('major', '')}")
print(f"FROM: {data.get('from', {}).get('names', [{}])[-1].get('name', '')}")
print(f"TO: {data.get('to', {}).get('names', [{}])[-1].get('name', '')}")

for group_name, group_list in (data.get("groups", {}) or {}).items():
    print(f"\nGROUP: {group_name}")
    for group in group_list:
        instr = group.get("instruction", {}) or {}
        instr_type = instr.get("type", "")
        instr_sel = instr.get("selectionType", "")
        instr_conj = instr.get("conjunction", "")
        if instr_type or instr_sel or instr_conj:
            print(f"  Instruction: {instr_type} / {instr_sel} / {instr_conj}")

        sections = group.get("sections", []) or []
        for s_idx, section in enumerate(sections):
            print(f"  Section {s_idx + 1} (choose ONE from these options):")
            for o_idx, item in enumerate(section):
                course = item.get("course", {}) if isinstance(item, dict) else {}
                t_key = course_key(course)
                print(f"    Option {o_idx + 1}: {fmt_course(course)}")

                sources = target_to_sources.get(t_key, [])
                if not sources:
                    print("      De Anza options: (no articulation listed)")
                    continue
                print("      De Anza options:")
                for s in sources:
                    label = s.get("group", "")
                    prefix = s["course"].get("prefix", "")
                    number = s["course"].get("courseNumber", "")
                    title = s["course"].get("courseTitle", "")
                    if label:
                        print(f"        - [{label}] {prefix} {number} — {title}")
                    else:
                        print(f"        - {prefix} {number} — {title}")
