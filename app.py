import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

import markdown
from markupsafe import Markup
from flask import Flask, g, jsonify, redirect, render_template, request, url_for

from generate_notebook import generate_notebook

app = Flask(__name__)


@app.template_filter("md")
def markdown_filter(text):
    html = markdown.markdown(
        text,
        extensions=["fenced_code", "codehilite", "tables"],
        extension_configs={
            "codehilite": {
                "css_class": "highlight",
                "guess_lang": False,
                "linenums": False,
            },
        },
    )
    return Markup(html)

DB_PATH = "data/progress.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS progress (
            lesson_id TEXT PRIMARY KEY,
            status TEXT DEFAULT 'not_started',
            notes TEXT DEFAULT '',
            completed_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS glossary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.commit()
    db.close()


def slugify(text):
    slug = text.lower().strip().replace(' ', '-')
    return re.sub(r'[^a-z0-9-]', '', slug)


def load_curriculum():
    with open("data/curriculum.json") as f:
        return json.load(f)


def get_progress_map(db):
    rows = db.execute("SELECT lesson_id, status, notes FROM progress").fetchall()
    return {r["lesson_id"]: {"status": r["status"], "notes": r["notes"]} for r in rows}


def compute_stats(curriculum, progress_map):
    total = 0
    completed = 0
    in_progress = 0
    total_hours = 0
    completed_hours = 0

    phase_stats = []

    for phase in curriculum["phases"]:
        p_total = 0
        p_completed = 0
        p_hours = 0
        p_completed_hours = 0

        for module in phase["modules"]:
            for lesson in module["lessons"]:
                total += 1
                p_total += 1
                hours = lesson.get("est_hours", 1)
                total_hours += hours
                p_hours += hours

                status = progress_map.get(lesson["id"], {}).get("status", "not_started")
                if status == "completed":
                    completed += 1
                    p_completed += 1
                    completed_hours += hours
                    p_completed_hours += hours
                elif status == "in_progress":
                    in_progress += 1

        phase_stats.append(
            {
                "id": phase["id"],
                "title": phase["title"],
                "total": p_total,
                "completed": p_completed,
                "percent": round(p_completed / p_total * 100) if p_total else 0,
                "hours": p_hours,
                "completed_hours": p_completed_hours,
            }
        )

    return {
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "percent": round(completed / total * 100) if total else 0,
        "total_hours": total_hours,
        "completed_hours": completed_hours,
        "phases": phase_stats,
    }


@app.route("/")
def index():
    db = get_db()
    curriculum = load_curriculum()
    progress_map = get_progress_map(db)
    stats = compute_stats(curriculum, progress_map)
    return render_template(
        "index.html", curriculum=curriculum, stats=stats, progress=progress_map
    )


@app.route("/phase/<phase_id>")
def phase_detail(phase_id):
    db = get_db()
    curriculum = load_curriculum()
    progress_map = get_progress_map(db)

    phase = next((p for p in curriculum["phases"] if p["id"] == phase_id), None)
    if not phase:
        return "Phase not found", 404

    # Compute module stats
    for module in phase["modules"]:
        m_total = len(module["lessons"])
        m_completed = sum(
            1
            for l in module["lessons"]
            if progress_map.get(l["id"], {}).get("status") == "completed"
        )
        module["_total"] = m_total
        module["_completed"] = m_completed
        module["_percent"] = round(m_completed / m_total * 100) if m_total else 0

    stats = compute_stats(curriculum, progress_map)
    return render_template(
        "phase.html", phase=phase, stats=stats, progress=progress_map
    )


def load_content():
    content = {}
    content_dir = Path("data/content")
    if content_dir.exists():
        for f in content_dir.glob("*.json"):
            with open(f) as fh:
                content.update(json.load(fh))
    return content


def find_lesson(curriculum, lesson_id):
    for phase in curriculum["phases"]:
        for module in phase["modules"]:
            for i, lesson in enumerate(module["lessons"]):
                if lesson["id"] == lesson_id:
                    prev_l = module["lessons"][i - 1] if i > 0 else None
                    next_l = module["lessons"][i + 1] if i < len(module["lessons"]) - 1 else None
                    return phase, module, lesson, prev_l, next_l
    return None, None, None, None, None


@app.route("/lesson/<lesson_id>")
def lesson_detail(lesson_id):
    db = get_db()
    curriculum = load_curriculum()
    progress_map = get_progress_map(db)
    content_map = load_content()

    phase, module, lesson, prev_l, next_l = find_lesson(curriculum, lesson_id)
    if not lesson:
        return "Lesson not found", 404

    content = content_map.get(lesson_id, {})
    status = progress_map.get(lesson_id, {}).get("status", "not_started")
    notes = progress_map.get(lesson_id, {}).get("notes", "")

    return render_template(
        "lesson.html",
        phase=phase,
        module=module,
        lesson=lesson,
        content=content,
        status=status,
        notes=notes,
        prev_lesson=prev_l,
        next_lesson=next_l,
    )


@app.route("/update", methods=["POST"])
def update_progress():
    db = get_db()
    lesson_id = request.form["lesson_id"]
    status = request.form["status"]
    redirect_url = request.form.get("redirect", "/")

    db.execute(
        """
        INSERT INTO progress (lesson_id, status, completed_at, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(lesson_id) DO UPDATE SET
            status = excluded.status,
            completed_at = CASE WHEN excluded.status = 'completed' THEN CURRENT_TIMESTAMP ELSE completed_at END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (lesson_id, status),
    )
    db.commit()
    return redirect(redirect_url)


@app.route("/notes", methods=["POST"])
def update_notes():
    db = get_db()
    lesson_id = request.form["lesson_id"]
    notes = request.form["notes"]
    redirect_url = request.form.get("redirect", "/")

    db.execute(
        """
        INSERT INTO progress (lesson_id, notes, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(lesson_id) DO UPDATE SET
            notes = excluded.notes,
            updated_at = CURRENT_TIMESTAMP
        """,
        (lesson_id, notes),
    )
    db.commit()
    return redirect(redirect_url)


JUPYTER_PORT = 8888
NOTEBOOK_DIR = Path("notebooks")


@app.route("/notebook/<lesson_id>")
def open_notebook(lesson_id):
    curriculum = load_curriculum()
    content_map = load_content()

    phase, module, lesson, _, _ = find_lesson(curriculum, lesson_id)
    if not lesson:
        return "Lesson not found", 404

    content = content_map.get(lesson_id, {})
    if not content.get("body"):
        return "No content for this lesson yet", 404

    NOTEBOOK_DIR.mkdir(exist_ok=True)
    nb_path = NOTEBOOK_DIR / f"{lesson_id}.ipynb"

    import nbformat

    nb = generate_notebook(
        lesson_id,
        lesson["title"],
        content["body"],
        content.get("exercises", []),
    )
    with open(nb_path, "w") as f:
        nbformat.write(nb, f)

    return redirect(f"http://localhost:{JUPYTER_PORT}/notebooks/{lesson_id}.ipynb")


@app.route("/reset", methods=["POST"])
def reset_progress():
    db = get_db()
    db.execute("DELETE FROM progress")
    db.commit()
    return redirect("/")


@app.route("/api/glossary")
def api_glossary():
    db = get_db()
    rows = db.execute("SELECT term, slug FROM glossary").fetchall()
    return jsonify({r["term"]: r["slug"] for r in rows})


@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.get_json()
    highlighted = data.get("highlighted", "")
    question = data.get("question", "")
    prompt = (
        f"The user is studying backend development and highlighted: {highlighted}. "
        f"Question: {question}. Give a concise explanation under 200 words."
    )
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    answer = None
    for attempt in range(2):
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--model", "opus"],
                capture_output=True,
                text=True,
                timeout=120,
                input="",
                env=env,
            )
            if result.returncode == 0:
                answer = result.stdout.strip()
                break
        except subprocess.TimeoutExpired:
            pass
        if attempt < 1:
            time.sleep(2)
    if not answer:
        return jsonify({"error": "Failed to get response from Claude"}), 500
    term = highlighted.strip()
    slug = slugify(term)
    db = get_db()
    db.execute(
        """
        INSERT INTO glossary (term, slug, question, answer)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            term = excluded.term,
            question = excluded.question,
            answer = excluded.answer,
            created_at = CURRENT_TIMESTAMP
        """,
        (term, slug, question, answer),
    )
    db.commit()
    answer_html = markdown.markdown(answer, extensions=["fenced_code", "codehilite", "tables"])
    return jsonify({"answer": answer_html})


@app.route("/glossary")
def glossary_index():
    db = get_db()
    rows = db.execute("SELECT * FROM glossary ORDER BY term ASC").fetchall()
    return render_template("glossary_index.html", entries=rows)


@app.route("/glossary/<slug>")
def glossary_term(slug):
    db = get_db()
    entry = db.execute("SELECT * FROM glossary WHERE slug = ?", (slug,)).fetchone()
    if not entry:
        return "Term not found", 404
    return render_template("glossary_term.html", entry=entry)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5055)
