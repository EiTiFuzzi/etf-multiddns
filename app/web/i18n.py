"""
Sehr schlanke Mehrsprachigkeit fuer das Web-UI (kein Flask-Babel noetig).

Die Sprache wird per Cookie ("lang") gespeichert und muss serverseitig
bekannt sein, bevor Templates gerendert werden (im Gegensatz zum Farb-
Theme, das rein clientseitig per localStorage funktioniert). Siehe
app/web/app.py: get_lang() liest das Cookie, ein Context-Processor stellt
t() und current_lang in jedem Template zur Verfuegung.
"""

from __future__ import annotations

LANGUAGES = ["de", "en"]
DEFAULT_LANG = "de"

LANGUAGE_LABELS = {"de": "Deutsch", "en": "English"}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "brand": "ETF-MultiDDNS",
        "nav.menu": "Menü",
        "nav.pin": "Menü fixieren",
        "nav.dashboard": "Dashboard",
        "nav.add_record": "Record hinzufügen",
        "nav.settings": "Einstellungen",
        "nav.logs": "Logs",
        "nav.logout": "Abmelden",
        "footer.tagline": "Dynamic DNS für",
        "footer.and": "und",
        "footer.version": "Version",
        "theme.light": "Hell",
        "theme.dark": "Dunkel",
        "theme.system": "System",
        "theme.label": "Darstellung",
        "lang.label": "Sprache",
        # Dashboard
        "dashboard.title": "Dashboard",
        "dashboard.no_token": "Es ist noch kein API-Token konfiguriert.",
        "dashboard.no_token_cta": "Jetzt in den Einstellungen hinterlegen",
        "dashboard.last_run_error": "Letzter Durchlauf mit Fehler:",
        "dashboard.card_ipv4": "Öffentliche IPv4",
        "dashboard.card_ipv6": "Öffentliche IPv6",
        "dashboard.card_last_run": "Letzter Abgleich",
        "dashboard.card_interval": "Prüfintervall",
        "dashboard.unknown": "unbekannt",
        "dashboard.never": "noch nie",
        "dashboard.sync_now": "Jetzt synchronisieren",
        "dashboard.records_title": "Verwaltete Records",
        "dashboard.no_records": "Noch keine Records konfiguriert.",
        "dashboard.no_records_cta": "Jetzt einen anlegen",
        "dashboard.th_host": "Host",
        "dashboard.th_type": "Typ",
        "dashboard.th_proxy_status": "Proxy-Status",
        "dashboard.proxy_status_proxied": "Mit Proxy",
        "dashboard.proxy_status_dns_only": "Nur DNS",
        "dashboard.th_ttl": "TTL",
        "dashboard.th_current_ip": "Aktuelle IP",
        "dashboard.th_status": "Status",
        "dashboard.th_last_sync": "Letzter Abgleich",
        "dashboard.th_active": "Aktiv",
        "dashboard.th_provider": "Provider",
        "dashboard.btn_on": "An",
        "dashboard.btn_off": "Aus",
        "dashboard.btn_edit": "Bearbeiten",
        "dashboard.btn_delete": "Löschen",
        "dashboard.confirm_delete": "Record wirklich beim DNS-Provider löschen?",
        "dashboard.confirm_disable": "Record wirklich deaktivieren? Der DNS-Record wird dabei beim Provider gelöscht (bleibt aber in dieser Liste erhalten und kann jederzeit wieder aktiviert werden).",
        "dashboard.filter_search": "Host suchen…",
        "dashboard.filter_all": "Alle",
        "dashboard.filter_reset": "Filter zurücksetzen",
        "dashboard.no_matches": "Keine Records entsprechen den aktuellen Filtern.",
        "status.unchanged": "unverändert",
        "status.created": "erstellt",
        "status.updated": "aktualisiert",
        "status.error": "fehler",
        "status.pending": "ausstehend",
        "status.disabled": "deaktiviert",
        # Record hinzufügen
        "new_record.title": "Record hinzufügen",
        "new_record.domains_error": "Domains konnten nicht geladen werden:",
        "new_record.label_provider": "DNS-Provider",
        "new_record.provider_cloudflare_not_configured": (
            "Für Cloudflare ist noch kein API-Token hinterlegt - in den Einstellungen nachtragen."
        ),
        "new_record.label_domain": "Domain",
        "new_record.domain_placeholder": "Domain wählen …",
        "new_record.label_subdomain": "Subdomain (leer lassen für Root-Domain)",
        "new_record.label_type": "Typ",
        "new_record.label_ttl": "TTL (Sekunden)",
        "new_record.label_comment": "Kommentar",
        "new_record.label_proxied": "Über Cloudflare proxen (orange Wolke)",
        "new_record.proxied_hint": (
            "Wenn aktiv, läuft der Traffic über Cloudflares Proxy (Performance/DDoS-Schutz, "
            "die tatsächliche IP wird verborgen). Wenn deaktiviert, zeigt der Record direkt "
            "auf die öffentliche IP (\"DNS only\", graue Wolke)."
        ),
        "new_record.btn_create": "Anlegen",
        "new_record.btn_cancel": "Abbrechen",
        "new_record.hint": (
            "Hinweis: Bei Domain Chief muss die Domain \"Hosted DNS\" verwenden (d.h. die "
            "Nameserver von Domain Chief müssen aktiv sein); bei Cloudflare muss die Domain "
            "als Zone im gewählten Account liegen. Existiert der Record schon, wird er beim "
            "nächsten Abgleich automatisch übernommen und auf die aktuelle öffentliche IP "
            "aktualisiert."
        ),
        # Vorhandene Records importieren
        "import.title": "Vorhandene Records importieren",
        "import.intro": (
            "Durchsucht alle Domains bei den konfigurierten Providern nach A-/AAAA-Records, "
            "die schon jetzt auf die ermittelte öffentliche IP zeigen, aber hier noch nicht "
            "verwaltet werden - zum Übernehmen einfach auswählen und importieren."
        ),
        "import.no_provider": "Es ist noch kein DNS-Provider konfiguriert.",
        "import.no_provider_cta": "Jetzt in den Einstellungen einrichten",
        "import.no_public_ip": (
            "Öffentliche IPv4/IPv6 konnte nicht ermittelt werden - es können daher keine "
            "passenden Records gefunden werden."
        ),
        "import.no_candidates": (
            "Keine importierbaren Records gefunden. Entweder werden bereits alle passenden "
            "Records hier verwaltet, oder es zeigt (noch) kein vorhandener Record beim Provider "
            "auf Ihre aktuelle öffentliche IP."
        ),
        "import.select_all": "Alle auswählen",
        "import.btn_import": "Ausgewählte importieren",
        # Record bearbeiten
        "edit_record.title": "Record bearbeiten",
        "edit_record.btn_save": "Speichern",
        "edit_record.hint": (
            "Hinweis: Wird der Typ oder der Provider geändert, legt der nächste Abgleich "
            "automatisch einen neuen DNS-Record beim (neuen) Provider an und entfernt den "
            "alten dort, wo er vorher war. Änderungen an TTL, Kommentar und Proxy-Status "
            "werden ebenfalls erst beim nächsten Abgleich übernommen (Domain und Subdomain "
            "können hier nicht geändert werden - dafür den Record löschen und neu anlegen)."
        ),
        # Einstellungen
        "settings.title": "Einstellungen",
        "settings.domainchief_title": "Domain Chief",
        "settings.env_notice": (
            "API-Token und Team-ID werden über Umgebungsvariablen (DOMAINCHIEF_API_TOKEN / "
            "DOMAINCHIEF_TEAM_ID) gesetzt und können hier nicht überschrieben werden."
        ),
        "settings.label_token": "Domain Chief API-Token",
        "settings.token_placeholder_set": "bereits gesetzt",
        "settings.token_hint": "Personal Access Token erstellen:",
        "settings.token_scopes_hint": "Benötigte Scopes:",
        "settings.label_team": "Team-ID (optional, nur bei Personal Access Token nötig falls nicht das Standard-Team verwendet werden soll)",
        "settings.cloudflare_title": "Cloudflare",
        "settings.cloudflare_env_notice": (
            "Der Cloudflare API-Token wird über die Umgebungsvariable CLOUDFLARE_API_TOKEN "
            "gesetzt und kann hier nicht überschrieben werden."
        ),
        "settings.cloudflare_label_token": "Cloudflare API-Token",
        "settings.cloudflare_token_hint": "API-Token erstellen:",
        "settings.cloudflare_token_scopes_hint": "Benötigte Berechtigungen:",
        "settings.general_title": "Allgemein",
        "settings.label_interval": "Prüfintervall (Sekunden, minimal 60)",
        "settings.label_timezone": "Zeitzone",
        "settings.timezone_system_default": "Systemstandard (UTC)",
        "settings.timezone_hint": (
            "Betrifft die Anzeige von Zeitstempeln (Dashboard, Logs). Wird sofort "
            "angewendet, ein Neustart des Containers ist nicht nötig."
        ),
        "settings.timezone_env_notice": (
            "Die Zeitzone wird über die Umgebungsvariable TZ gesetzt und kann hier "
            "nicht überschrieben werden."
        ),
        "settings.label_datetime_format": "Datum-/Zeitformat",
        "settings.datetime_format_hint": "Bestimmt, wie Zeitstempel im Dashboard und in den Logs angezeigt werden.",
        "settings.btn_save": "Speichern",
        "settings.btn_test": "Verbindung testen",
        "settings.btn_import": "Vorhandene Records importieren",
        "settings.testing": "Teste...",
        "settings.test_no_token": "Kein API-Token gesetzt.",
        "settings.test_success": "Verbindung erfolgreich.",
        "settings.webui_title": "Web-UI Zugangsdaten",
        "settings.webui_env_notice": (
            "Benutzername und Passwort werden über Umgebungsvariablen (WEBUI_USERNAME / "
            "WEBUI_PASSWORD) gesetzt und können hier nicht geändert werden."
        ),
        "settings.label_username": "Benutzername",
        "settings.label_new_password": "Neues Passwort (leer lassen, um es nicht zu ändern)",
        "settings.label_new_password2": "Neues Passwort bestätigen",
        "settings.webui_error_mismatch": "Die Passwörter stimmen nicht überein.",
        "settings.webui_error_short": "Das Passwort sollte mindestens 8 Zeichen lang sein.",
        "settings.webui_saved": "Zugangsdaten gespeichert.",
        "settings.btn_save_webui": "Zugangsdaten speichern",
        "settings.https_title": "HTTPS / Sichere Verbindung",
        "settings.https_intro": (
            "Zusätzlich zum bisherigen HTTP-Port ist das Web-UI optional auch verschlüsselt "
            "per HTTPS erreichbar (beide Ports funktionieren parallel). HTTPS-Port:"
        ),
        "settings.https_saved": "HTTPS-Einstellungen gespeichert.",
        "settings.https_enable": "HTTPS aktivieren",
        "settings.https_warning": (
            "Hinweis: Mit einem selbstsignierten Zertifikat zeigt der Browser beim Aufruf über "
            "HTTPS eine Sicherheitswarnung an (\"nicht vertrauenswürdig\") - das ist normal und "
            "kann bestätigt/als Ausnahme hinzugefügt werden. Wer das vermeiden möchte, kann "
            "stattdessen unten ein eigenes Zertifikat importieren."
        ),
        "settings.https_cert_source": "Zertifikatsquelle",
        "settings.https_source_self_signed": "Selbstsigniert (Standard)",
        "settings.https_source_custom": "Eigenes Zertifikat (siehe unten)",
        "settings.https_hostname_label": "Hostname/IP für das Zertifikat (optional)",
        "settings.https_hostname_hint": (
            "Wird als Zertifikatsname (CN/SAN) für das selbstsignierte Zertifikat verwendet, "
            "z.B. die eigene DDNS-Domain. Leer lassen für ein generisches Zertifikat "
            "(localhost/127.0.0.1). Wirkt sofort, ein Neustart des Containers ist nicht nötig."
        ),
        "settings.https_selfsigned_heading": "Aktuelles selbstsigniertes Zertifikat",
        "settings.https_cert_subject": "Name:",
        "settings.https_cert_valid_until": "Gültig bis:",
        "settings.https_cert_none": "Noch kein Zertifikat erzeugt.",
        "settings.https_btn_regenerate": "Zertifikat neu erzeugen",
        "settings.https_custom_title": "Eigenes Zertifikat importieren",
        "settings.https_custom_hint": (
            "Zertifikat und privater Schlüssel im PEM-Format (z.B. von Let's Encrypt oder einer "
            "internen CA), unverschlüsselt (ohne Passphrase). Nach dem Import wird die "
            "Zertifikatsquelle automatisch auf \"Eigenes Zertifikat\" umgestellt."
        ),
        "settings.https_upload_cert_label": "Zertifikat (PEM, .crt/.pem)",
        "settings.https_upload_key_label": "Privater Schlüssel (PEM, .key)",
        "settings.https_choose_file": "Datei auswählen",
        "settings.https_no_file_chosen": "Keine Datei ausgewählt",
        "settings.https_btn_upload": "Importieren",
        "settings.https_btn_remove_custom": "Eigenes Zertifikat entfernen",
        "settings.https_no_custom_cert": "Noch kein eigenes Zertifikat importiert.",
        "settings.https_err_no_custom_cert": (
            "Als Zertifikatsquelle ist \"Eigenes Zertifikat\" ausgewählt, aber es wurde noch "
            "keines importiert - HTTPS bleibt deaktiviert, bis eines hochgeladen wurde."
        ),
        "settings.https_err_port_in_use": (
            "Der HTTPS-Port konnte nicht gestartet werden (möglicherweise bereits belegt)."
        ),
        "settings.https_err_cert_error": "Das Zertifikat konnte nicht geladen werden.",
        "settings.https_err_invalid_cert": "Ungültiges Zertifikat (kein gültiges PEM).",
        "settings.https_err_invalid_key": "Ungültiger privater Schlüssel (kein gültiges, unverschlüsseltes PEM).",
        "settings.https_err_key_mismatch": "Zertifikat und privater Schlüssel passen nicht zusammen.",
        "settings.https_err_missing_files": "Bitte sowohl Zertifikat als auch privaten Schlüssel auswählen.",
        "settings.totp_title": "Zwei-Faktor-Authentifizierung (2FA)",
        "settings.totp_intro": (
            "Schützt die Anmeldung zusätzlich zu Benutzername/Passwort mit einem zeitbasierten Code "
            "(TOTP) aus einer Authenticator-App (z.B. Google Authenticator, Aegis, 1Password)."
        ),
        "settings.totp_btn_enable": "2FA aktivieren",
        "settings.totp_status_enabled": "2FA ist aktiviert.",
        "settings.totp_low_recovery_codes": "Nur noch wenige Wiederherstellungscodes übrig.",
        "settings.totp_label_code_confirm": "Code aus der Authenticator-App (oder ein Wiederherstellungscode)",
        "settings.totp_btn_disable": "2FA deaktivieren",
        "settings.totp_confirm_disable": "2FA wirklich deaktivieren? Die Anmeldung ist danach wieder nur über Benutzername/Passwort geschützt.",
        "settings.totp_btn_regenerate_recovery": "Wiederherstellungscodes neu erzeugen",
        "settings.totp_confirm_regenerate": "Neue Wiederherstellungscodes erzeugen? Die bisherigen werden dabei ungültig.",
        "settings.totp_disabled_notice": "2FA wurde deaktiviert.",
        "settings.totp_error_invalid_code": "Ungültiger Code.",
        "settings.totp_setup_title": "2FA einrichten",
        "settings.totp_setup_intro": (
            "QR-Code mit einer Authenticator-App scannen (oder den Schlüssel manuell eintragen), dann "
            "den angezeigten 6-stelligen Code hier eingeben, um die Einrichtung zu bestätigen."
        ),
        "settings.totp_manual_key_label": "Manueller Schlüssel:",
        "settings.totp_label_code": "6-stelliger Code",
        "settings.totp_btn_confirm": "Bestätigen & aktivieren",
        "settings.totp_btn_cancel": "Abbrechen",
        "settings.totp_recovery_title": "Wiederherstellungscodes",
        "settings.totp_recovery_warning": (
            "Diese Codes werden nur einmal angezeigt. Jeder Code funktioniert einmalig als Ersatz für "
            "den Authenticator-Code, falls das Gerät mit der Authenticator-App verloren geht oder "
            "nicht verfügbar ist. An einem sicheren Ort aufbewahren (z.B. Passwort-Manager, Ausdruck)."
        ),
        "settings.totp_btn_done": "Fertig, weiter zu den Einstellungen",
        # Logs
        "logs.title": "Logs",
        # Login / Setup
        "login.title": "Anmelden",
        "login.label_username": "Benutzername",
        "login.label_password": "Passwort",
        "login.btn": "Anmelden",
        "login.error": "Benutzername oder Passwort falsch.",
        "login2fa.title": "Zwei-Faktor-Authentifizierung",
        "login2fa.intro": "Bitte den 6-stelligen Code aus der Authenticator-App eingeben.",
        "login2fa.label_code": "Code",
        "login2fa.btn": "Bestätigen",
        "login2fa.error": "Ungültiger Code.",
        "login2fa.recovery_hint": "Kein Zugriff auf die Authenticator-App? Ein Wiederherstellungscode funktioniert hier ebenfalls.",
        "setup.title": "Ersteinrichtung",
        "setup.intro": (
            "Lege einen Benutzernamen und ein Passwort für den Zugriff auf dieses Web-UI fest. "
            "Das Web-UI ist noch nicht abgesichert - bitte jetzt einrichten."
        ),
        "setup.label_username": "Benutzername",
        "setup.label_password": "Passwort (mindestens 8 Zeichen)",
        "setup.label_password2": "Passwort bestätigen",
        "setup.btn": "Einrichten & anmelden",
        "setup.error_empty": "Benutzername und Passwort dürfen nicht leer sein.",
        "setup.error_mismatch": "Die Passwörter stimmen nicht überein.",
        "setup.error_short": "Das Passwort sollte mindestens 8 Zeichen lang sein.",
    },
    "en": {
        "brand": "ETF-MultiDDNS",
        "nav.menu": "Menu",
        "nav.pin": "Pin menu",
        "nav.dashboard": "Dashboard",
        "nav.add_record": "Add record",
        "nav.settings": "Settings",
        "nav.logs": "Logs",
        "nav.logout": "Log out",
        "footer.tagline": "Dynamic DNS for",
        "footer.and": "and",
        "footer.version": "Version",
        "theme.light": "Light",
        "theme.dark": "Dark",
        "theme.system": "System",
        "theme.label": "Appearance",
        "lang.label": "Language",
        # Dashboard
        "dashboard.title": "Dashboard",
        "dashboard.no_token": "No API token configured yet.",
        "dashboard.no_token_cta": "Set it up in Settings now",
        "dashboard.last_run_error": "Last sync failed:",
        "dashboard.card_ipv4": "Public IPv4",
        "dashboard.card_ipv6": "Public IPv6",
        "dashboard.card_last_run": "Last sync",
        "dashboard.card_interval": "Check interval",
        "dashboard.unknown": "unknown",
        "dashboard.never": "never",
        "dashboard.sync_now": "Sync now",
        "dashboard.records_title": "Managed records",
        "dashboard.no_records": "No records configured yet.",
        "dashboard.no_records_cta": "Add one now",
        "dashboard.th_host": "Host",
        "dashboard.th_type": "Type",
        "dashboard.th_proxy_status": "Proxy Status",
        "dashboard.proxy_status_proxied": "Proxied",
        "dashboard.proxy_status_dns_only": "DNS only",
        "dashboard.th_ttl": "TTL",
        "dashboard.th_current_ip": "Current IP",
        "dashboard.th_status": "Status",
        "dashboard.th_last_sync": "Last sync",
        "dashboard.th_active": "Active",
        "dashboard.th_provider": "Provider",
        "dashboard.btn_on": "On",
        "dashboard.btn_off": "Off",
        "dashboard.btn_edit": "Edit",
        "dashboard.btn_delete": "Delete",
        "dashboard.confirm_delete": "Really delete this record at its DNS provider?",
        "dashboard.confirm_disable": "Really disable this record? Its DNS record will be deleted at the provider (it stays in this list and can be re-enabled at any time).",
        "dashboard.filter_search": "Search host…",
        "dashboard.filter_all": "All",
        "dashboard.filter_reset": "Reset filters",
        "dashboard.no_matches": "No records match the current filters.",
        "status.unchanged": "unchanged",
        "status.created": "created",
        "status.updated": "updated",
        "status.error": "error",
        "status.pending": "pending",
        "status.disabled": "disabled",
        # Add record
        "new_record.title": "Add record",
        "new_record.domains_error": "Could not load domains:",
        "new_record.label_provider": "DNS provider",
        "new_record.provider_cloudflare_not_configured": (
            "No API token configured for Cloudflare yet - add one in Settings."
        ),
        "new_record.label_domain": "Domain",
        "new_record.domain_placeholder": "Select a domain …",
        "new_record.label_subdomain": "Subdomain (leave empty for the root domain)",
        "new_record.label_type": "Type",
        "new_record.label_ttl": "TTL (seconds)",
        "new_record.label_comment": "Comment",
        "new_record.label_proxied": "Proxy through Cloudflare (orange cloud)",
        "new_record.proxied_hint": (
            "When enabled, traffic is routed through Cloudflare's proxy (performance/DDoS "
            "protection, hides the actual IP). When disabled, the record points directly at "
            "the public IP (\"DNS only\", grey cloud)."
        ),
        "new_record.btn_create": "Create",
        "new_record.btn_cancel": "Cancel",
        "new_record.hint": (
            "Note: with Domain Chief, the domain must use \"Hosted DNS\" (i.e. Domain Chief's "
            "nameservers must be active); with Cloudflare, the domain must exist as a zone in "
            "the selected account. If the record already exists, it will be picked up "
            "automatically on the next sync and updated to the current public IP."
        ),
        # Import existing records
        "import.title": "Import existing records",
        "import.intro": (
            "Scans every domain at the configured providers for A/AAAA records that already "
            "point at the detected public IP but aren't managed here yet - select the ones "
            "you want and import them."
        ),
        "import.no_provider": "No DNS provider configured yet.",
        "import.no_provider_cta": "Set one up in Settings now",
        "import.no_public_ip": (
            "Could not determine the public IPv4/IPv6 address - no matching records can be "
            "found without it."
        ),
        "import.no_candidates": (
            "No importable records found. Either every matching record is already managed "
            "here, or no existing record at the provider points at your current public IP "
            "(yet)."
        ),
        "import.select_all": "Select all",
        "import.btn_import": "Import selected",
        # Edit record
        "edit_record.title": "Edit record",
        "edit_record.btn_save": "Save",
        "edit_record.hint": (
            "Note: changing the type or provider makes the next sync create a new DNS record "
            "at the (new) provider and remove the old one wherever it used to be. Changes to "
            "TTL, comment and proxy status are also applied on the next sync (the domain and "
            "subdomain can't be changed here - delete the record and add it again instead)."
        ),
        # Settings
        "settings.title": "Settings",
        "settings.domainchief_title": "Domain Chief",
        "settings.env_notice": (
            "The API token and team ID are set via environment variables (DOMAINCHIEF_API_TOKEN / "
            "DOMAINCHIEF_TEAM_ID) and cannot be overridden here."
        ),
        "settings.label_token": "Domain Chief API token",
        "settings.token_placeholder_set": "already set",
        "settings.token_hint": "Create a personal access token:",
        "settings.token_scopes_hint": "Required scopes:",
        "settings.label_team": "Team ID (optional, only needed with a personal access token if the default team shouldn't be used)",
        "settings.cloudflare_title": "Cloudflare",
        "settings.cloudflare_env_notice": (
            "The Cloudflare API token is set via the CLOUDFLARE_API_TOKEN environment variable "
            "and cannot be overridden here."
        ),
        "settings.cloudflare_label_token": "Cloudflare API token",
        "settings.cloudflare_token_hint": "Create an API token:",
        "settings.cloudflare_token_scopes_hint": "Required permissions:",
        "settings.general_title": "General",
        "settings.label_interval": "Check interval (seconds, minimum 60)",
        "settings.label_timezone": "Time zone",
        "settings.timezone_system_default": "System default (UTC)",
        "settings.timezone_hint": (
            "Affects how timestamps are displayed (dashboard, logs). Applied "
            "immediately, no container restart required."
        ),
        "settings.timezone_env_notice": (
            "The time zone is set via the TZ environment variable and cannot be "
            "overridden here."
        ),
        "settings.label_datetime_format": "Date/time format",
        "settings.datetime_format_hint": "Controls how timestamps are displayed on the dashboard and in the logs.",
        "settings.btn_save": "Save",
        "settings.btn_test": "Test connection",
        "settings.btn_import": "Import existing records",
        "settings.testing": "Testing...",
        "settings.test_no_token": "No API token set.",
        "settings.test_success": "Connection successful.",
        "settings.webui_title": "Web UI credentials",
        "settings.webui_env_notice": (
            "The username and password are set via environment variables (WEBUI_USERNAME / "
            "WEBUI_PASSWORD) and cannot be changed here."
        ),
        "settings.label_username": "Username",
        "settings.label_new_password": "New password (leave empty to keep it unchanged)",
        "settings.label_new_password2": "Confirm new password",
        "settings.webui_error_mismatch": "The passwords do not match.",
        "settings.webui_error_short": "The password should be at least 8 characters long.",
        "settings.webui_saved": "Credentials saved.",
        "settings.btn_save_webui": "Save credentials",
        "settings.https_title": "HTTPS / Secure connection",
        "settings.https_intro": (
            "In addition to the existing HTTP port, the Web UI is optionally also reachable "
            "encrypted over HTTPS (both ports work in parallel). HTTPS port:"
        ),
        "settings.https_saved": "HTTPS settings saved.",
        "settings.https_enable": "Enable HTTPS",
        "settings.https_warning": (
            "Note: with a self-signed certificate, the browser shows a security warning "
            "(\"not trusted\") when opening the HTTPS URL - that's expected and can be "
            "confirmed/added as an exception. To avoid that, import your own certificate below "
            "instead."
        ),
        "settings.https_cert_source": "Certificate source",
        "settings.https_source_self_signed": "Self-signed (default)",
        "settings.https_source_custom": "Custom certificate (see below)",
        "settings.https_hostname_label": "Hostname/IP for the certificate (optional)",
        "settings.https_hostname_hint": (
            "Used as the self-signed certificate's name (CN/SAN), e.g. your own DDNS domain. "
            "Leave empty for a generic certificate (localhost/127.0.0.1). Applied immediately, "
            "no container restart required."
        ),
        "settings.https_selfsigned_heading": "Current self-signed certificate",
        "settings.https_cert_subject": "Name:",
        "settings.https_cert_valid_until": "Valid until:",
        "settings.https_cert_none": "No certificate generated yet.",
        "settings.https_btn_regenerate": "Regenerate certificate",
        "settings.https_custom_title": "Import a custom certificate",
        "settings.https_custom_hint": (
            "Certificate and private key in PEM format (e.g. from Let's Encrypt or an internal "
            "CA), unencrypted (no passphrase). After importing, the certificate source is "
            "automatically switched to \"Custom certificate\"."
        ),
        "settings.https_upload_cert_label": "Certificate (PEM, .crt/.pem)",
        "settings.https_upload_key_label": "Private key (PEM, .key)",
        "settings.https_choose_file": "Choose file",
        "settings.https_no_file_chosen": "No file chosen",
        "settings.https_btn_upload": "Import",
        "settings.https_btn_remove_custom": "Remove custom certificate",
        "settings.https_no_custom_cert": "No custom certificate imported yet.",
        "settings.https_err_no_custom_cert": (
            "\"Custom certificate\" is selected as the certificate source, but none has been "
            "imported yet - HTTPS stays disabled until one is uploaded."
        ),
        "settings.https_err_port_in_use": "Could not start the HTTPS port (it may already be in use).",
        "settings.https_err_cert_error": "The certificate could not be loaded.",
        "settings.https_err_invalid_cert": "Invalid certificate (not valid PEM).",
        "settings.https_err_invalid_key": "Invalid private key (not a valid, unencrypted PEM key).",
        "settings.https_err_key_mismatch": "The certificate and private key don't belong together.",
        "settings.https_err_missing_files": "Please select both a certificate and a private key.",
        "settings.totp_title": "Two-factor authentication (2FA)",
        "settings.totp_intro": (
            "Protects the login with an additional time-based code (TOTP) from an authenticator app "
            "(e.g. Google Authenticator, Aegis, 1Password), on top of username/password."
        ),
        "settings.totp_btn_enable": "Enable 2FA",
        "settings.totp_status_enabled": "2FA is enabled.",
        "settings.totp_low_recovery_codes": "Only a few recovery codes left.",
        "settings.totp_label_code_confirm": "Code from your authenticator app (or a recovery code)",
        "settings.totp_btn_disable": "Disable 2FA",
        "settings.totp_confirm_disable": "Really disable 2FA? The login will then only be protected by username/password again.",
        "settings.totp_btn_regenerate_recovery": "Regenerate recovery codes",
        "settings.totp_confirm_regenerate": "Generate new recovery codes? The existing ones will stop working.",
        "settings.totp_disabled_notice": "2FA has been disabled.",
        "settings.totp_error_invalid_code": "Invalid code.",
        "settings.totp_setup_title": "Set up 2FA",
        "settings.totp_setup_intro": (
            "Scan the QR code with an authenticator app (or enter the key manually), then enter the "
            "6-digit code it shows here to confirm setup."
        ),
        "settings.totp_manual_key_label": "Manual key:",
        "settings.totp_label_code": "6-digit code",
        "settings.totp_btn_confirm": "Confirm & enable",
        "settings.totp_btn_cancel": "Cancel",
        "settings.totp_recovery_title": "Recovery codes",
        "settings.totp_recovery_warning": (
            "These codes are shown only once. Each one works a single time as a substitute for the "
            "authenticator code, in case the device with the authenticator app is lost or unavailable. "
            "Keep them somewhere safe (e.g. a password manager, a printout)."
        ),
        "settings.totp_btn_done": "Done, back to Settings",
        # Logs
        "logs.title": "Logs",
        # Login / Setup
        "login.title": "Sign in",
        "login.label_username": "Username",
        "login.label_password": "Password",
        "login.btn": "Sign in",
        "login.error": "Incorrect username or password.",
        "login2fa.title": "Two-factor authentication",
        "login2fa.intro": "Please enter the 6-digit code from your authenticator app.",
        "login2fa.label_code": "Code",
        "login2fa.btn": "Confirm",
        "login2fa.error": "Invalid code.",
        "login2fa.recovery_hint": "No access to your authenticator app? A recovery code also works here.",
        "setup.title": "Initial setup",
        "setup.intro": (
            "Choose a username and password to protect access to this web UI. "
            "It isn't secured yet - please set this up now."
        ),
        "setup.label_username": "Username",
        "setup.label_password": "Password (at least 8 characters)",
        "setup.label_password2": "Confirm password",
        "setup.btn": "Set up & sign in",
        "setup.error_empty": "Username and password must not be empty.",
        "setup.error_mismatch": "The passwords do not match.",
        "setup.error_short": "The password should be at least 8 characters long.",
    },
}


def translator(lang: str):
    """Gibt eine t(key)-Funktion gebunden an die uebergebene Sprache zurueck."""
    table = TRANSLATIONS.get(lang, TRANSLATIONS[DEFAULT_LANG])
    fallback = TRANSLATIONS[DEFAULT_LANG]

    def t(key: str) -> str:
        return table.get(key, fallback.get(key, key))

    return t
