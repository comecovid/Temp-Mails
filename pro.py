import os
import random
import string
import requests
from flask import Flask, render_template_string, redirect, url_for, session, request, flash

app = Flask(__name__)
app.secret_key = os.urandom(24)  # for session storage (change to a fixed secret for production)

MAILTM_BASE = "https://api.mail.tm"

# ---------- helpers ----------
def random_username(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def get_domains():
    resp = requests.get(f"{MAILTM_BASE}/domains")
    resp.raise_for_status()
    members = resp.json().get("hydra:member", [])
    return [d["domain"] for d in members]

def register_account(address, password):
    # create account
    payload = {"address": address, "password": password}
    resp = requests.post(f"{MAILTM_BASE}/accounts", json=payload)
    # If account already exists, mail.tm returns 422. We'll ignore that and try to obtain token anyway.
    return resp

def get_token(address, password):
    payload = {"address": address, "password": password}
    resp = requests.post(f"{MAILTM_BASE}/token", json=payload)
    resp.raise_for_status()
    return resp.json()["token"]

def get_messages(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{MAILTM_BASE}/messages", headers=headers)
    resp.raise_for_status()
    items = resp.json().get("hydra:member", [])
    return items

def get_message_detail(token, msg_id):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{MAILTM_BASE}/messages/{msg_id}", headers=headers)
    resp.raise_for_status()
    return resp.json()

# ---------- simple pages ----------
INDEX_HTML = """
<!doctype html>
<title>Temp Mail Demo</title>
<h1>Temporary Email Demo</h1>
{% with messages = get_flashed_messages() %}
  {% if messages %}
    <ul style="color: red;">
      {% for m in messages %}<li>{{m}}</li>{% endfor %}
    </ul>
  {% endif %}
{% endwith %}
{% if email %}
  <p><strong>Email:</strong> {{ email }}</p>
  <p><a href="{{ url_for('inbox') }}">Open inbox</a></p>
  <form action="{{ url_for('create') }}" method="post" style="display:inline;">
    <button type="submit">Generate new email</button>
  </form>
{% else %}
  <p>No temp email yet.</p>
  <form action="{{ url_for('create') }}" method="post">
    <button type="submit">Generate temp email</button>
  </form>
{% endif %}
"""

INBOX_HTML = """
<!doctype html>
<title>Inbox - {{email}}</title>
<h1>Inbox for {{ email }}</h1>
<p><a href="{{ url_for('index') }}">Back</a></p>
{% if messages %}
  <ul>
  {% for m in messages %}
    <li>
      <strong>{{ m.subject or "(no subject)" }}</strong>
      — from {{ m.from[0].address if m.from else "unknown" }}
      — <a href="{{ url_for('message_detail', msg_id=m.id) }}">view</a>
    </li>
  {% endfor %}
  </ul>
{% else %}
  <p>No messages yet. Try sending an email to <strong>{{ email }}</strong>.</p>
{% endif %}
"""

MESSAGE_HTML = """
<!doctype html>
<title>Message</title>
<h1>{{ msg.subject or "(no subject)" }}</h1>
<p><em>From: {{ msg.from[0].address if msg.from else "unknown" }}</em></p>
<p><a href="{{ url_for('inbox') }}">Back to inbox</a></p>
<hr>
<p><strong>Text:</strong></p>
<pre>{{ msg.text }}</pre>
<hr>
<p><strong>HTML (if any):</strong></p>
<div style="border:1px solid #ddd;padding:10px;">
  {{ msg.html|safe }}
</div>
"""

# ---------- routes ----------
@app.route("/")
def index():
    email = session.get("email")
    return render_template_string(INDEX_HTML, email=email)

@app.route("/create", methods=["POST"])
def create():
    # generate username and domain
    try:
        domains = get_domains()
    except Exception as e:
        flash(f"Failed to fetch domains: {e}")
        return redirect(url_for("index"))

    if not domains:
        flash("No domains returned by mail.tm")
        return redirect(url_for("index"))

    domain = random.choice(domains)
    username = random_username(10)
    email = f"{username}@{domain}"
    password = random_username(12)  # just a random password

    try:
        resp = register_account(email, password)
        # If create returned an error (e.g., already exists), we still try to get token
        # If creating succeeded or account existed, obtain token:
        token = get_token(email, password)
    except requests.HTTPError as e:
        # try to extract token anyway if account existed earlier with same creds
        try:
            token = get_token(email, password)
        except Exception as e2:
            flash(f"Account registration/token failed: {e} / {e2}")
            return redirect(url_for("index"))
    except Exception as e:
        flash(f"Unexpected error: {e}")
        return redirect(url_for("index"))

    # save to session
    session["email"] = email
    session["password"] = password
    session["token"] = token

    return redirect(url_for("index"))

@app.route("/inbox")
def inbox():
    token = session.get("token")
    email = session.get("email")
    if not token or not email:
        flash("No email registered — generate one first.")
        return redirect(url_for("index"))
    try:
        messages = get_messages(token)
    except Exception as e:
        flash(f"Failed to fetch messages: {e}")
        return redirect(url_for("index"))
    return render_template_string(INBOX_HTML, messages=messages, email=email)

@app.route("/message/<msg_id>")
def message_detail(msg_id):
    token = session.get("token")
    if not token:
        flash("No token available.")
        return redirect(url_for("index"))
    try:
        msg = get_message_detail(token, msg_id)
    except Exception as e:
        flash(f"Failed to fetch message: {e}")
        return redirect(url_for("inbox"))
    return render_template_string(MESSAGE_HTML, msg=msg)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
