"""
Generate a Jupyter notebook from a lesson's body content.

For each code block in the lesson:
1. Markdown cell with the surrounding explanation
2. Collapsible hint containing the code
3. Empty code cell for the user to type in
"""

import json
import os
import re

try:
    import nbformat
    from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell
except ImportError:
    nbformat = None


def parse_body_to_blocks(body: str) -> list[dict]:
    """Parse a lesson body into alternating markdown and code blocks."""
    blocks = []
    code_pattern = re.compile(r'```python\n(.*?)```', re.DOTALL)

    last_end = 0
    for match in code_pattern.finditer(body):
        start, end = match.span()

        text_before = body[last_end:start].strip()
        if text_before:
            blocks.append({'type': 'markdown', 'text': text_before})

        code = match.group(1).strip()
        blocks.append({'type': 'code', 'code': code})

        last_end = end

    remaining = body[last_end:].strip()
    if remaining:
        blocks.append({'type': 'markdown', 'text': remaining})

    return blocks


def generate_notebook(lesson_id: str, lesson_title: str, body: str,
                      exercises: list = None):
    """Generate a Jupyter notebook from lesson content."""
    nb = new_notebook()
    nb.metadata['kernelspec'] = {
        'display_name': 'Python 3',
        'language': 'python',
        'name': 'python3'
    }

    nb.cells.append(new_markdown_cell(f"# {lesson_id} - {lesson_title}"))

    blocks = parse_body_to_blocks(body)

    for block in blocks:
        if block['type'] == 'markdown':
            nb.cells.append(new_markdown_cell(block['text']))
        elif block['type'] == 'code':
            hint_md = (
                "<details>\n"
                "<summary>Show code</summary>\n\n"
                "```python\n"
                f"{block['code']}\n"
                "```\n"
                "</details>"
            )
            nb.cells.append(new_markdown_cell(hint_md))
            nb.cells.append(new_code_cell(""))

    if exercises:
        nb.cells.append(new_markdown_cell("---\n# Exercises"))
        for i, ex in enumerate(exercises, 1):
            ex_md = f"### Exercise {i}: {ex['title']}\n\n{ex['description']}"
            nb.cells.append(new_markdown_cell(ex_md))

            if ex.get('hint'):
                hint_md = (
                    "<details>\n"
                    "<summary>Show hint</summary>\n\n"
                    f"{ex['hint']}\n"
                    "</details>"
                )
                nb.cells.append(new_markdown_cell(hint_md))

            nb.cells.append(new_code_cell(""))

    return nb


def generate_all():
    """Generate notebooks for all lessons."""
    os.makedirs('notebooks', exist_ok=True)

    with open('data/curriculum.json') as f:
        curriculum = json.load(f)

    total = 0
    skipped = 0
    for phase in curriculum['phases']:
        phase_num = int(phase['id'].split('-')[1])
        json_path = f'data/content/phase-{phase_num}.json'
        try:
            with open(json_path) as f:
                content = json.load(f)
        except FileNotFoundError:
            continue

        for module in phase['modules']:
            for lesson in module['lessons']:
                lid = lesson['id']
                lesson_data = content.get(lid)
                if not lesson_data or 'body' not in lesson_data:
                    skipped += 1
                    continue

                nb = generate_notebook(
                    lid,
                    lesson['title'],
                    lesson_data['body'],
                    lesson_data.get('exercises', [])
                )
                out_path = f'notebooks/{lid}.ipynb'
                with open(out_path, 'w') as f:
                    nbformat.write(nb, f)
                total += 1

    print(f"Generated {total} notebooks, skipped {skipped}")


if __name__ == '__main__':
    generate_all()
