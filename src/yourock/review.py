from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, redirect, render_template_string, request, send_from_directory, url_for

from .config import ProjectConfig
from .markdown import generate_markdown
from .storage import SHOUTOUT_FIELDS, read_rows, utc_now, write_rows
from .utils import youtube_url

VALID_STATUSES = ("pending", "verified", "rejected")

PAGE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Command Zone You Rock Review</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { max-width: 1100px; margin: 2rem auto; padding: 0 1rem 6rem; }
    nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; }
    .notice { border: 1px solid #39845c; background: #39845c22; border-radius: 10px; padding: .75rem 1rem; margin: 1rem 0; }
    .save-bar {
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      border: 1px solid #7777;
      border-radius: 12px;
      padding: .75rem 1rem;
      margin: 1rem 0;
      background: Canvas;
      box-shadow: 0 4px 18px #0003;
    }
    .save-bar p { margin: 0; }
    .save-bar button, .save-bottom button { margin: 0; font-weight: 700; }
    .dirty { font-size: .9rem; opacity: .75; }
    .card { border: 1px solid #7777; border-radius: 12px; padding: 1rem; margin: 1rem 0; }
    .meta { opacity: .75; }
    img { max-width: 100%; border-radius: 8px; margin: .75rem 0; }
    label { display: block; margin: .65rem 0 .25rem; font-weight: 600; }
    input, textarea, select { width: 100%; box-sizing: border-box; padding: .55rem; }
    button { padding: .65rem 1rem; cursor: pointer; }
    button:disabled { cursor: wait; opacity: .7; }
    .context { white-space: pre-wrap; line-height: 1.45; }
    .save-bottom { display: flex; justify-content: flex-end; margin-top: 1.5rem; }
  </style>
</head>
<body>
  <h1>Command Zone “You Rock” Review</h1>
  <nav>
    <a href="/?status=pending">Pending ({{ counts.pending }})</a>
    <a href="/?status=verified">Verified ({{ counts.verified }})</a>
    <a href="/?status=rejected">Rejected ({{ counts.rejected }})</a>
    <a href="/?status=all">All ({{ counts.all }})</a>
  </nav>

  {% if saved is not none %}
    <div class="notice">Saved {{ saved }} candidate{{ '' if saved == 1 else 's' }} and rebuilt YOU_ROCK.md.</div>
  {% endif %}

  {% if rows %}
    <form method="post" action="{{ url_for('save_all') }}" id="review-form">
      <input type="hidden" name="return_status" value="{{ selected }}">

      <div class="save-bar">
        <div>
          <p><strong>Review every visible candidate, then save once.</strong></p>
          <span class="dirty" id="dirty-state">No unsaved changes</span>
        </div>
        <button type="submit">Save all changes</button>
      </div>

      {% for row in rows %}
        <section class="card">
          <input type="hidden" name="candidate_id" value="{{ row.candidate_id }}">
          <h2>{{ row.name or 'Name not detected' }}</h2>
          <p class="meta">
            Episode {{ '#' + row.episode_number if row.episode_number else '' }} — {{ row.episode_title }}<br>
            <a href="{{ row.url }}" target="_blank" rel="noopener">Open at {{ row.timestamp_display }}</a>
          </p>
          {% if row.screenshot %}
            <img src="{{ url_for('screenshot', filename=row.screenshot_name) }}" alt="Candidate frame">
          {% endif %}
          <p class="context">{{ row.context }}</p>

          <label for="name-{{ loop.index }}">Name</label>
          <input id="name-{{ loop.index }}" name="name" value="{{ row.name }}" autocomplete="off">

          <label for="status-{{ loop.index }}">Status</label>
          <select id="status-{{ loop.index }}" name="status">
            {% for option in valid_statuses %}
              <option value="{{ option }}" {% if row.status == option %}selected{% endif %}>{{ option|capitalize }}</option>
            {% endfor %}
          </select>

          <label for="notes-{{ loop.index }}">Notes</label>
          <textarea id="notes-{{ loop.index }}" name="notes" rows="2">{{ row.notes }}</textarea>
        </section>
      {% endfor %}

      <div class="save-bottom">
        <button type="submit">Save all changes</button>
      </div>
    </form>
  {% else %}
    <p>No candidates in this view.</p>
  {% endif %}

  <script>
    (() => {
      const form = document.getElementById('review-form');
      if (!form) return;

      const state = document.getElementById('dirty-state');
      let dirty = false;
      let submitting = false;

      const markDirty = () => {
        dirty = true;
        state.textContent = 'Unsaved changes';
      };

      form.addEventListener('input', markDirty);
      form.addEventListener('change', markDirty);
      form.addEventListener('submit', () => {
        submitting = true;
        state.textContent = 'Saving…';
        form.querySelectorAll('button[type="submit"]').forEach((button) => {
          button.disabled = true;
          button.textContent = 'Saving…';
        });
      });

      window.addEventListener('beforeunload', (event) => {
        if (!dirty || submitting) return;
        event.preventDefault();
        event.returnValue = '';
      });
    })();
  </script>
</body>
</html>
"""


def create_app(config: ProjectConfig) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        selected = request.args.get("status", "pending")
        if selected not in (*VALID_STATUSES, "all"):
            selected = "pending"

        all_rows = read_rows(config.shoutouts_csv)
        counts = {
            "pending": sum(row.get("status") == "pending" for row in all_rows),
            "verified": sum(row.get("status") == "verified" for row in all_rows),
            "rejected": sum(row.get("status") == "rejected" for row in all_rows),
            "all": len(all_rows),
        }
        rows = all_rows if selected == "all" else [row for row in all_rows if row.get("status") == selected]
        rows.sort(key=_review_sort_key, reverse=True)
        for row in rows:
            row["url"] = youtube_url(row.get("video_id", ""), row.get("timestamp_seconds", "0"))
            screenshot_value = row.get("screenshot", "")
            row["screenshot_name"] = Path(screenshot_value).name if screenshot_value else ""

        saved_value = request.args.get("saved")
        try:
            saved = int(saved_value) if saved_value is not None else None
        except ValueError:
            saved = None

        return render_template_string(
            PAGE,
            rows=rows,
            counts=counts,
            selected=selected,
            saved=saved,
            valid_statuses=VALID_STATUSES,
        )

    @app.post("/save-all")
    def save_all():
        candidate_ids = request.form.getlist("candidate_id")
        names = request.form.getlist("name")
        statuses = request.form.getlist("status")
        notes = request.form.getlist("notes")

        lengths = {len(candidate_ids), len(names), len(statuses), len(notes)}
        if len(lengths) != 1:
            abort(400, description="The review form fields were incomplete or misaligned.")

        rows = read_rows(config.shoutouts_csv)
        rows_by_id = {row.get("candidate_id", ""): row for row in rows}
        now = utc_now()
        updated = 0

        for candidate_id, name, status, note in zip(candidate_ids, names, statuses, notes, strict=True):
            target = rows_by_id.get(candidate_id)
            if target is None:
                continue

            clean_status = status if status in VALID_STATUSES else "pending"
            new_values = {
                "name": name.strip(),
                "status": clean_status,
                "notes": note.strip(),
            }
            changed = any(target.get(field, "") != value for field, value in new_values.items())
            target.update(new_values)
            if changed:
                target["updated_at"] = now
                updated += 1

        write_rows(config.shoutouts_csv, SHOUTOUT_FIELDS, rows)
        generate_markdown(config.shoutouts_csv, config.markdown_file)

        return_status = request.form.get("return_status", "pending")
        if return_status not in (*VALID_STATUSES, "all"):
            return_status = "pending"
        return redirect(url_for("index", status=return_status, saved=updated))

    @app.post("/candidate/<candidate_id>")
    def update_candidate(candidate_id: str):
        """Keep the original single-candidate endpoint for compatibility."""
        rows = read_rows(config.shoutouts_csv)
        target = next((row for row in rows if row.get("candidate_id") == candidate_id), None)
        if target is None:
            abort(404)

        status = request.form.get("status", "pending")
        if status not in VALID_STATUSES:
            status = "pending"
        target["name"] = request.form.get("name", "").strip()
        target["status"] = status
        target["notes"] = request.form.get("notes", "").strip()
        target["updated_at"] = utc_now()
        write_rows(config.shoutouts_csv, SHOUTOUT_FIELDS, rows)
        generate_markdown(config.shoutouts_csv, config.markdown_file)
        return redirect(url_for("index", status=target["status"], saved=1))

    @app.get("/screenshots/<path:filename>")
    def screenshot(filename: str):
        return send_from_directory(config.screenshots_dir, filename)

    return app


def _review_sort_key(row: dict[str, str]) -> tuple[int, float]:
    try:
        episode = int(row.get("episode_number") or 0)
    except ValueError:
        episode = 0
    try:
        timestamp = float(row.get("timestamp_seconds") or 0)
    except ValueError:
        timestamp = 0.0
    return episode, timestamp
