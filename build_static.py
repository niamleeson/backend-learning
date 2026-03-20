#!/usr/bin/env python3
"""Build static HTML site into docs/ for GitHub Pages."""

import json
import os
import shutil
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"

# Base URL for GitHub Pages (repo name)
BASE_URL = "/backend-learning"


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


def load_curriculum(lang):
    filename = DATA / ("curriculum-js.json" if lang == "javascript" else "curriculum.json")
    with open(filename) as f:
        return json.load(f)


def load_content(lang):
    content = {}
    content_dir = DATA / ("content-js" if lang == "javascript" else "content")
    if content_dir.exists():
        for f in content_dir.glob("*.json"):
            with open(f) as fh:
                content.update(json.load(fh))
    return content


def compute_stats(curriculum):
    """Compute stats with empty progress (static site has no tracking)."""
    total = 0
    total_hours = 0
    phase_stats = []

    for phase in curriculum["phases"]:
        p_total = 0
        p_hours = 0
        for module in phase["modules"]:
            for lesson in module["lessons"]:
                total += 1
                p_total += 1
                hours = lesson.get("est_hours", 1)
                total_hours += hours
                p_hours += hours

        phase_stats.append({
            "id": phase["id"],
            "title": phase["title"],
            "total": p_total,
            "completed": 0,
            "percent": 0,
            "hours": p_hours,
            "completed_hours": 0,
        })

    return {
        "total": total,
        "completed": 0,
        "in_progress": 0,
        "percent": 0,
        "total_hours": total_hours,
        "completed_hours": 0,
        "phases": phase_stats,
    }


def find_lesson(curriculum, lesson_id):
    for phase in curriculum["phases"]:
        for module in phase["modules"]:
            for i, lesson in enumerate(module["lessons"]):
                if lesson["id"] == lesson_id:
                    prev_l = module["lessons"][i - 1] if i > 0 else None
                    next_l = module["lessons"][i + 1] if i < len(module["lessons"]) - 1 else None
                    return phase, module, lesson, prev_l, next_l
    return None, None, None, None, None


def build():
    # Clean output
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir()

    # Setup Jinja2
    env = Environment(loader=FileSystemLoader(str(ROOT / "templates_static")))
    env.filters["md"] = markdown_filter

    # Copy static assets
    static_src = ROOT / "static"
    static_dst = DOCS / "static"
    if static_src.exists():
        shutil.copytree(static_src, static_dst)

    # Build both language variants
    for lang in ("python", "javascript"):
        curriculum = load_curriculum(lang)
        content_map = load_content(lang)
        stats = compute_stats(curriculum)
        progress = {}
        lang_prefix = "js" if lang == "javascript" else "py"

        # Index page
        tpl = env.get_template("index.html")
        html = tpl.render(
            curriculum=curriculum,
            stats=stats,
            progress=progress,
            lang=lang,
            base_url=BASE_URL,
            lang_prefix=lang_prefix,
        )
        if lang == "python":
            (DOCS / "index.html").write_text(html)
        (DOCS / f"index-{lang_prefix}.html").write_text(html)

        # Phase pages
        for phase in curriculum["phases"]:
            for module in phase["modules"]:
                m_total = len(module["lessons"])
                module["_total"] = m_total
                module["_completed"] = 0
                module["_percent"] = 0

            tpl = env.get_template("phase.html")
            html = tpl.render(
                phase=phase,
                stats=stats,
                progress=progress,
                lang=lang,
                base_url=BASE_URL,
                lang_prefix=lang_prefix,
            )
            phase_dir = DOCS / "phase"
            phase_dir.mkdir(exist_ok=True)
            (phase_dir / f"{phase['id']}-{lang_prefix}.html").write_text(html)
            if lang == "python":
                (phase_dir / f"{phase['id']}.html").write_text(html)

        # Lesson pages
        for phase in curriculum["phases"]:
            for module in phase["modules"]:
                for i, lesson in enumerate(module["lessons"]):
                    content = content_map.get(lesson["id"], {})
                    prev_l = module["lessons"][i - 1] if i > 0 else None
                    next_l = module["lessons"][i + 1] if i < len(module["lessons"]) - 1 else None

                    tpl = env.get_template("lesson.html")
                    html = tpl.render(
                        phase=phase,
                        module=module,
                        lesson=lesson,
                        content=content,
                        status="not_started",
                        notes="",
                        prev_lesson=prev_l,
                        next_lesson=next_l,
                        lang=lang,
                        base_url=BASE_URL,
                        lang_prefix=lang_prefix,
                    )
                    lesson_dir = DOCS / "lesson"
                    lesson_dir.mkdir(exist_ok=True)
                    (lesson_dir / f"{lesson['id']}-{lang_prefix}.html").write_text(html)
                    if lang == "python":
                        (lesson_dir / f"{lesson['id']}.html").write_text(html)

    # Create .nojekyll for GitHub Pages
    (DOCS / ".nojekyll").touch()

    # Count generated files
    html_files = list(DOCS.rglob("*.html"))
    print(f"Built {len(html_files)} HTML pages into docs/")


if __name__ == "__main__":
    build()
