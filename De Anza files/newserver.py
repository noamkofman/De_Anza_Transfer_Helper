from flask import Flask, request, render_template, session, redirect, url_for, jsonify
from jinja2 import ChoiceLoader, FileSystemLoader
import os
import json
import re
from fuzzywuzzy import process

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=BASE_DIR,
)
app.jinja_loader = ChoiceLoader([
    FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    FileSystemLoader(BASE_DIR),
])
app.secret_key = "dev-change-this"

def _display_name(folder_name: str) -> str:
    return folder_name.replace("_", " ")


def load_campus_names() -> list[str]:
    uc_root = find_uc_root(BASE_DIR)
    names = []
    for d in os.listdir(uc_root):
        if not os.path.isdir(os.path.join(uc_root, d)) or d.startswith("."):
            continue
        names.append(_display_name(d))
    return sorted(names)


def resolve_folder_name(display_name: str) -> str:
    uc_root = find_uc_root(BASE_DIR)
    candidates = [
        d for d in os.listdir(uc_root)
        if os.path.isdir(os.path.join(uc_root, d)) and not d.startswith(".")
    ]
    lookup = {_display_name(d): d for d in candidates}
    return lookup.get(display_name, display_name)

def find_uc_root(start_dir: str) -> str:
    direct = os.path.join(start_dir, "uc_to_deanza")
    if os.path.isdir(direct):
        return direct
    legacy = os.path.join(start_dir, "De Anza files", "uc_to_deanza")
    if os.path.isdir(legacy):
        return legacy
    cur = start_dir
    for _ in range(4):
        candidate = os.path.join(cur, "De Anza files", "uc_to_deanza")
        if os.path.isdir(candidate):
            return candidate
        candidate = os.path.join(cur, "uc_to_deanza")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    raise FileNotFoundError("Could not locate 'uc_to_deanza' directory.")


def pick_latest_year_dir(campus_dir: str) -> str:
    entries = [d for d in os.listdir(campus_dir) if os.path.isdir(os.path.join(campus_dir, d))]
    year_dirs = []
    for d in entries:
        m = re.match(r"^(\d{4})_year_(\d+)$", d)
        if m:
            year_dirs.append((int(m.group(1)), int(m.group(2)), d))
    if year_dirs:
        year_dirs.sort(reverse=True)
        return os.path.join(campus_dir, year_dirs[0][2])
    return campus_dir


def load_major_choices(folder: str) -> list[str]:
    major_choices = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            result = data.get("result", {})
            major_name = result.get("name")
            if major_name:
                major_choices.append(major_name)
        except Exception:
            continue
    return major_choices


def build_bundles(sending: dict):
    groups = sending.get("items", []) or []
    if not groups:
        return []

    group_conjs = sending.get("courseGroupConjunctions", []) or []
    pos_to_conj = {}

    groups_sorted = sorted(groups, key=lambda g: g.get("position", 0))
    positions = [g.get("position", 0) for g in groups_sorted]
    for pos in positions[:-1]:
        pos_to_conj[pos] = "And"
    for gc in group_conjs:
        begin = gc.get("sendingCourseGroupBeginPosition")
        end = gc.get("sendingCourseGroupEndPosition")
        conj = gc.get("groupConjunction")
        if begin is None or end is None or not conj:
            continue
        for pos in positions:
            if begin <= pos < end:
                pos_to_conj[pos] = conj

    option_num = 1
    option_map = {}
    option_key_to_num = {}
    group_bundles_by_group = []

    for group in groups_sorted:
        label = group.get("courseConjunction", "") or "And"
        current_group_options = []
        for cls in group.get("items", []):
            c_prefix = cls.get("prefix", "")
            c_num = cls.get("courseNumber", "")
            c_title = cls.get("courseTitle", "")
            if "HONORS" in c_title:
                continue
            key = (c_prefix, c_num)
            if key in option_key_to_num:
                existing_num = option_key_to_num[key]
                if existing_num not in current_group_options:
                    current_group_options.append(existing_num)
                continue
            option_key_to_num[key] = option_num
            option_map[option_num] = {
                "prefix": c_prefix,
                "number": c_num,
                "title": c_title,
            }
            current_group_options.append(option_num)
            option_num += 1

        if not current_group_options:
            continue
        if label == "Or":
            group_bundles = [[opt] for opt in current_group_options]
        else:
            group_bundles = [current_group_options]
        group_bundles_by_group.append(group_bundles)

    if not group_bundles_by_group:
        return []

    bundles = group_bundles_by_group[0]
    for i, group_bundles in enumerate(group_bundles_by_group[1:], start=0):
        conj = pos_to_conj.get(positions[i], "And")
        if conj == "And":
            combined = []
            for b in bundles:
                for g in group_bundles:
                    combined.append(b + g)
            bundles = combined
        else:
            bundles = bundles + group_bundles

    # Convert bundle option nums into course dicts
    bundles_courses = []
    for bundle in bundles:
        courses = []
        for opt in bundle:
            picked = option_map.get(opt)
            if picked:
                courses.append(picked)
        if courses:
            bundles_courses.append(courses)
    return bundles_courses


def build_requirements(folder: str, major_name: str):
    requirements = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        result = data.get("result", {})
        if result.get("name", "") != major_name:
            continue
        for entry in result.get("articulations", []):
            art = entry.get("articulation", {})
            target = art.get("course", {})
            t_prefix = target.get("prefix", "")
            t_num = target.get("courseNumber", "")
            t_desc = target.get("courseTitle", "")
            if not (t_prefix or t_num or t_desc):
                continue
            sending = art.get("sendingArticulation", {})
            bundles = build_bundles(sending)
            requirements.append({
                "label": f"{t_prefix} {t_num} - {t_desc}",
                "bundles": bundles,
            })
    return requirements



@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/schools", methods=["GET"])
def schools():
    return jsonify(load_campus_names())


@app.route("/majors", methods=["GET"])
def majors():
    school_query = request.args.get("school", "").strip()
    if not school_query:
        return jsonify([])
    campus_names = load_campus_names()
    match, _ = process.extractOne(school_query, campus_names)
    uc_root = find_uc_root(BASE_DIR)
    folder_name = resolve_folder_name(match)
    campus_dir = os.path.join(uc_root, folder_name)
    if not os.path.isdir(campus_dir):
        return jsonify([])
    folder = pick_latest_year_dir(campus_dir)
    return jsonify(load_major_choices(folder))


@app.route("/plan", methods=["POST"])
def plan():
    if request.form.get("clear_saved") == "1":
        session["saved_plans"] = []
        return redirect(url_for("index"))

    school_query = request.form.get("school_query", "").strip()
    major_query = request.form.get("major_query", "").strip()
    if not school_query or not major_query:
        return render_template("index.html")

    campus_names = load_campus_names()
    match, _ = process.extractOne(school_query, campus_names)
    uc_root = find_uc_root(BASE_DIR)
    folder_name = resolve_folder_name(match)
    campus_dir = os.path.join(uc_root, folder_name)
    if not os.path.isdir(campus_dir):
        return f"No campus folder found at {campus_dir}", 400
    folder = pick_latest_year_dir(campus_dir)

    major_choices = load_major_choices(folder)
    if not major_choices:
        return "No majors found.", 400
    maj_match, _ = process.extractOne(major_query, major_choices)

    requirements = build_requirements(folder, maj_match)

    # If generate flag, apply selections
    plan_lines = []
    if request.form.get("generate") == "1":
        selected = []
        for i, req in enumerate(requirements):
            bundles = req["bundles"]
            if not bundles:
                continue
            choice_raw = request.form.get(f"req_{i}", "1")
            try:
                choice = int(choice_raw)
            except ValueError:
                choice = 1
            choice = max(1, min(choice, len(bundles)))
            for c in bundles[choice - 1]:
                selected.append(f"{c['prefix']} {c['number']} - {c['title']}")
        plan_lines = sorted(set(selected))
        plan_path = os.path.join(BASE_DIR, "plan.txt")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("\n".join(plan_lines))
        saved = session.get("saved_plans", [])
        saved.append({
            "school_label": match,
            "major_label": maj_match,
            "plan_lines": plan_lines,
        })
        session["saved_plans"] = saved

    return render_template(
        "plan.html",
        school_label=match,
        major_label=maj_match,
        school_query=school_query,
        major_query=major_query,
        requirements=requirements,
        plan_lines=plan_lines,
        saved_plans=session.get("saved_plans", []),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
