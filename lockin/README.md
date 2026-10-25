LockIn: study system powered by NVIDIA NIM

Run locally
  pip install -r requirements.txt
  copy .env.example to .env and set NVIDIA_API_KEY
  streamlit run app.py

Deploy on Streamlit Community Cloud
  1. Push this folder to a GitHub repo
  2. New app, main file path: app.py
  3. Advanced settings, Secrets, paste the contents of .streamlit/secrets.toml.example with your real key
  4. Keep the app private or limit viewers, the database is shared by everyone who opens it
  5. The server disk resets on reboot, so use the sidebar Backup / restore to download and re-upload lockin.db
