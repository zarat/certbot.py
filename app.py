from flask import Flask, request, render_template_string, redirect, url_for, flash, send_file
import subprocess
import os
import zipfile
import ssl
import OpenSSL
from OpenSSL import crypto

import pytz
from datetime import datetime

local_tz = pytz.timezone("Europe/Vienna")
local_time = datetime.now(local_tz)
print("Aktuelle Zeit:", local_time.strftime('%Y-%m-%d %H:%M:%S'))

app = Flask(__name__)
app.secret_key = 'supergeheimespasswort'  # ändere das in etwas Sicheres (todo)

# Konfiguration
CLOUDFLARE_INI_PATH = "/etc/letsencrypt/cloudflare.ini"
CERTBOT_PATH = "/etc/letsencrypt/live/"

# HTML-Templates für die Formulare
HTML_INDEX = """
<!doctype html>
<title>Flask Certbot Interface</title>
<h2>Willkommen zum Certbot Interface</h2>
<ul>
  <li><a href="{{ url_for('request_certificate') }}">Zertifikat anfordern</a></li>
  <li><a href="{{ url_for('download_certificates') }}">Zertifikat herunterladen</a></li>
  <li><a href="{{ url_for('view_certificate_details') }}">Zertifikatsdetails anzeigen</a></li>
</ul>
"""

HTML_FORM_REQUEST = """
<!doctype html>
<title>Zertifikat anfordern</title>
<h2>Zertifikat anfordern</h2>

<a href="{{ url_for('index') }}">Zurück zum Index</a>
<br><br>

<form method=post action="{{ url_for('request_certificate') }}">
  Domain(s) (komma-getrennt): <input type=text name=domains><br><br>
  <input type=submit value="Zertifikat anfordern">
</form>

{% with messages = get_flashed_messages() %}
  {% if messages %}
    <ul style="color: red;">
      {% for message in messages %}
        <li>{{ message }}</li>
      {% endfor %}
    </ul>
  {% endif %}
{% endwith %}

"""

HTML_FORM_DOWNLOAD = """
<!doctype html>
<title>Zertifikat herunterladen</title>
<h2>Zertifikat herunterladen (ZIP)</h2>

<a href="{{ url_for('index') }}">Zurück zum Index</a>
<br><br>

<form method=post action="{{ url_for('download_certificates') }}">
  Domain:
  <select name="domain">
    {% for domain in domains %}
      <option value="{{ domain }}">{{ domain }}</option>
    {% endfor %}
  </select><br><br>
  <input type=submit value="Zertifikat als ZIP herunterladen">
</form>

{% with messages = get_flashed_messages() %}
  {% if messages %}
    <ul style="color: red;">
      {% for message in messages %}
        <li>{{ message }}</li>
      {% endfor %}
    </ul>
  {% endif %}
{% endwith %}

"""

HTML_FORM_CERTIFICATE_DETAILS = """
<!doctype html>
<title>Zertifikatsdetails anzeigen</title>
<h2>Zertifikatsdetails</h2>

<a href="{{ url_for('index') }}">Zurück zum Index</a>
<br><br>

<form method=post action="{{ url_for('view_certificate_details') }}">
  Domain:
  <select name="domain">
    {% for domain in domains %}
      <option value="{{ domain }}">{{ domain }}</option>
    {% endfor %}
  </select><br><br>
  <input type=submit value="Details anzeigen">
</form>

{% if certificate_details %}
  <h3>Details für {{ certificate_details['domain'] }} (UTC)</h3>
  <ul>
    <!-- <li>Erstellungsdatum: {{ certificate_details['creation_date'] }}</li>
    <li>Ablaufdatum: {{ certificate_details['expiration_date'] }}</li> -->
    <li>Gültig von: {{ certificate_details['valid_from'] }}</li>
    <li>Gültig bis: {{ certificate_details['valid_until'] }}</li>
    <!-- <li>Aussteller: {{ certificate_details['issuer'] }}</li> -->
  </ul>
  {% if certificate_details['is_expired'] %}
    <p style="color: red; font-weight: bold;">Achtung: Dieses Zertifikat ist abgelaufen!</p>
  {% endif %}
{% endif %}

"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_INDEX)

@app.route("/request_certificate", methods=["GET", "POST"])
def request_certificate():
    if request.method == "POST":
        domains_raw = request.form.get("domains", "")
        domains = [d.strip() for d in domains_raw.split(",") if d.strip()]
        if not domains:
            flash("Keine gültige Domain angegeben.")
            return redirect(url_for("request_certificate"))

        certbot_command = [
            "sudo", "certbot", "certonly",
            "--dns-cloudflare",
            f"--dns-cloudflare-credentials={CLOUDFLARE_INI_PATH}",
            "--non-interactive", "--agree-tos", "-m", "infra-it@akm.at",
        ] + sum([["-d", d] for d in domains], [])

        try:
            result = subprocess.run(certbot_command, capture_output=True, text=True, check=True)
            flash("Zertifikat erfolgreich angefordert.")
        except subprocess.CalledProcessError as e:
            flash("Fehler bei der Zertifikatsanforderung:")
            flash(e.stderr)

        return redirect(url_for("request_certificate"))

    return render_template_string(HTML_FORM_REQUEST)

@app.route("/download_certificates", methods=["GET", "POST"])
def download_certificates():
    # Alle verfügbaren Domains abrufen (die Ordner in /etc/letsencrypt/live/)
    domains = [d for d in os.listdir(CERTBOT_PATH) if os.path.isdir(os.path.join(CERTBOT_PATH, d))]

    if request.method == "POST":
        domain = request.form.get("domain", "").strip()

        if not domain:
            flash("Bitte eine gültige Domain angeben.")
            return redirect(url_for("download_certificates"))

        cert_path = os.path.join(CERTBOT_PATH, domain)

        # Überprüfen, ob das Zertifikat existiert
        if not os.path.exists(cert_path):
            flash("Zertifikate für diese Domain wurden noch nicht erstellt.")
            return redirect(url_for("download_certificates"))

        # ZIP-Datei erstellen
        zip_filename = f"/tmp/{domain}_certificates.zip"
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for foldername, subfolders, filenames in os.walk(cert_path):
                for filename in filenames:
                    file_path = os.path.join(foldername, filename)
                    zipf.write(file_path, os.path.relpath(file_path, cert_path))

        # ZIP-Datei zum Download bereitstellen
        return send_file(zip_filename, as_attachment=True)

    return render_template_string(HTML_FORM_DOWNLOAD, domains=domains)

@app.route("/view_certificate_details", methods=["GET", "POST"])
def view_certificate_details():
    # Alle verfügbaren Domains abrufen
    domains = [d for d in os.listdir(CERTBOT_PATH) if os.path.isdir(os.path.join(CERTBOT_PATH, d))]

    certificate_details = None
    if request.method == "POST":
        domain = request.form.get("domain", "").strip()

        if not domain:
            flash("Bitte eine gültige Domain angeben.")
            return redirect(url_for("view_certificate_details"))

        cert_path = os.path.join(CERTBOT_PATH, domain, "fullchain.pem")

        if not os.path.exists(cert_path):
            flash("Zertifikate für diese Domain wurden noch nicht erstellt.")
            return redirect(url_for("view_certificate_details"))

        # Zertifikatsdetails extrahieren
        certificate_details = get_certificate_details(cert_path)

    return render_template_string(HTML_FORM_CERTIFICATE_DETAILS, domains=domains, certificate_details=certificate_details)

def get_certificate_details(cert_path):
    """Extrahiere Details aus dem Zertifikat und prüfe, ob es abgelaufen ist"""
    with open(cert_path, 'rb') as cert_file:
        cert = crypto.load_certificate(crypto.FILETYPE_PEM, cert_file.read())

    # Erstellungsdatum und Ablaufdatum extrahieren
    valid_from_utc = datetime.strptime(cert.get_notBefore().decode('utf-8'), "%Y%m%d%H%M%SZ")
    valid_until_utc = datetime.strptime(cert.get_notAfter().decode('utf-8'), "%Y%m%d%H%M%SZ")

    issuer = cert.get_issuer().CN

    # Prüfen, ob das Zertifikat abgelaufen ist
    is_expired = datetime.utcnow() > valid_until_utc  # Vergleicht die aktuelle UTC-Zeit mit dem Ablaufdatum

    # Formatierung der Details im UTC-Format
    details = {
        'domain': cert.get_subject().CN,
        'creation_date': valid_from_utc.strftime('%Y-%m-%d '),
        'expiration_date': valid_until_utc.strftime('%Y-%m-%d '),
        'valid_from': valid_from_utc.strftime('%Y-%m-%d '),
        'valid_until': valid_until_utc.strftime('%Y-%m-%d '),
        'issuer': issuer,
        'is_expired': is_expired  # Zeigt an, ob das Zertifikat abgelaufen ist
    }

    return details

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
