LockIn: AI study system on NVIDIA NIM, multi-user, with admin panel

Models
  Everything (vision, teaching, grading) uses mistralai/mistral-large-4-1t-a52b.
  If a model is retired or unavailable (HTTP 410), the app tries backups. Admin Panel, System, Test the models shows what works.
  If every model returns 410 with no explanation, create a new NVIDIA key with the Public API Endpoints service ticked.
  NIM_REASONING=low is fastest. Set it to high for deeper (slower) reasoning.
  NIM_JSON_MODE=off skips the API's JSON mode (use it if the Admin speed test shows JSON mode is slow). The app repairs and retries broken JSON either way.
  NIM_HEDGE_SECONDS=6: if a request has not answered after 6 seconds, the same request is sent a second time and whichever answers first wins (0 turns it off). This cuts the long random waits on NVIDIA's shared servers.
  Vision: the best hosted vision models are tried in this order: Qwen3.5-397B, Nemotron 3.5 Super VL, Mistral Large 4. Marked papers are read by the top two and cross-checked.
  Admin Panel, System, Vision bake-off compares them on your own paper; set NIM_VISION_MODEL to put the winner first.
  Optional overrides: NIM_TEACHER_MODEL, NIM_VISION_MODEL, NIM_FAST_MODEL (comma-separated lists, first one wins).

Local run
  pip install -r requirements.txt
  copy .env.example to .env and fill it in (leave DATABASE_URL empty to use a local SQLite file)
  streamlit run app.py

Streamlit Community Cloud
  1. Push this folder to GitHub (the folder containing app.py)
  2. New app, main file path: app.py
  3. Advanced settings, Secrets: paste .streamlit/secrets.toml.example with your real values
  4. Deploy, then log in under Admin login with your MASTER_KEY

Permanent database (needed on Streamlit Cloud, whose disk resets)
  1. Create a free project at supabase.com
  2. Click Connect, choose Type URI and Method Transaction pooler, copy the string
  3. Put it in the DATABASE_URL secret (no backslashes, URL-encode special characters in the password)
  4. Choose the Supabase region closest to Streamlit Cloud (US East) for the fastest page loads

Changing the admin password
  Streamlit Cloud, Settings, Secrets, edit MASTER_KEY, Save.

Deleting data
  Admin Panel, Data: delete one student's data, whole tables, old records, or wipe all students.
