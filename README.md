**English** | [Deutsch](LIESMICH.md)

<p align="center">
  <img src="docs/logo.png" alt="ETF-MultiDDNS logo" width="480">
</p>

# ETF-MultiDDNS

A small Docker container that automatically updates A/AAAA records at [Domain Chief](https://domain.chief.app)
to your current public IP address - similar to
[cloudflare-ddns](https://github.com/timothymiller/cloudflare-ddns), just for Domain Chief instead of Cloudflare.

Includes:

- a background sync loop that checks your public IPv4/IPv6 address and automatically **creates**
  (if they don't exist yet) or **updates** (if the IP has changed) DNS records hosted at Domain Chief
- a Web UI for creating, enabling/disabling and **deleting** records, and viewing status and logs
- an optional CLI (`docker exec`) for managing via script/SSH

![Dashboard screenshot](docs/screenshot-dashboard.png)

## Requirements

- The affected domain(s) must use **Hosted DNS** at Domain Chief (i.e. Domain Chief's nameservers
  are active). Without Hosted DNS, the API can't manage records.
- A Domain Chief **Personal Access Token** (recommended for personal use) or a **Team Access Token**.

### Create a token

1. Personal Access Token: <https://domain.chief.app/api/token/create>
2. Required scopes: `domainchief:dns:read`, `domainchief:dns:write`, and `domainchief:domains:read`
   (the latter only so the Web UI can suggest a list of your domains when creating a record).
3. If your account has multiple teams and you don't want to use the default team: also set the team ID
   in the Web UI or via `DOMAINCHIEF_TEAM_ID`. Alternatively, use a **Team Access Token** (`ctt_...`)
   directly - that's automatically tied to a specific team.

## Start with Docker Compose (pre-built image)

```bash
cp .env.example .env   # optional, the token can also be set in the Web UI
# adjust the image name once in docker-compose.yml (username lowercased!),
# then:
docker compose up -d
```

The Web UI is then reachable at `http://<host>:8080`. If no token was set via an environment variable,
you can enter it there under **Settings** - including a "Test connection" button.
It's optionally also reachable encrypted via `https://<host>:8443` once enabled under **Settings ->
HTTPS** (see below) - both ports work in parallel.

The configuration (token if set via the UI, team ID, records, status) lives in `./config/config.json`
and survives container restarts, since the folder is mounted as a volume.

## Start with plain `docker run` (pre-built image, no build needed)

```bash
docker run -d \
  --name etf-multiddns \
  --restart unless-stopped \
  -p 8080:8080 \
  -p 8443:8443 \
  -e DOMAINCHIEF_API_TOKEN=ctp_your_token \
  -e CHECK_INTERVAL=300 \
  -v $(pwd)/config:/config \
  ghcr.io/<your-github-name-lowercased>/etf-multiddns:latest
```

(Drop the `-p 8443:8443` line if you don't plan on enabling HTTPS and don't want the port exposed.)

## Managing records

### Via the Web UI

- **Dashboard** (`/`): shows the currently detected public IPv4/IPv6, the time of the last sync, and
  the status of each managed record (unchanged / created / updated / error). A button lets you trigger
  an immediate sync without waiting for the interval. The "Add record" button leads to the create/edit
  form (no longer a separate menu item); in the record list, the pencil icon opens the same form in
  edit mode.
- **Add/edit record** (`/records/new` or `/records/<id>/edit`, a shared form): enter domain, subdomain
  (empty = root domain, e.g. just `example.com`), type (A/AAAA), TTL, and comment. When creating: if a
  matching record already exists at Domain Chief, it is adopted on the next sync (not created twice).
  When editing, only the domain is fixed (delete and recreate the record for that) - subdomain, type,
  TTL, and comment can be changed. If subdomain or type is changed, the next sync automatically creates
  a new DNS record at Domain Chief and removes the old one; plain TTL/comment changes are likewise only
  applied on the next sync.
- **Delete**: the trash-can button in the record list deletes the record both from the local
  configuration and directly at Domain Chief via the API.
- **Settings** (`/settings`): API token, team ID, check interval, timezone, and date/time format (for
  displaying timestamps), as well as the Web UI credentials (username/password).
- **Logs** (`/logs`): the most recent log lines from the sync loop.

### Login, appearance & language

- **Login:** On the very first visit to the Web UI, an initial setup wizard (`/setup`) guides you
  through creating a username and password. After that, every visit is protected via `/login` (session
  cookie, valid for 30 days). The "Log out" button in the top right lets you log out at any time, and
  the credentials can be changed under **Settings**.
  Alternatively, the username/password can be fixed via the `WEBUI_USERNAME` / `WEBUI_PASSWORD`
  environment variables (see `.env.example` or `docker-compose.yml`) - in that case the setup wizard is
  skipped and the fields in Settings are disabled.
- **Appearance:** In the top right you can choose between Light, Dark, and System (follows the
  operating system setting). The choice is stored in the browser (`localStorage`) and only applies
  locally to this device/browser.
- **Language:** The interface is available in German and English, switchable via "DE"/"EN" in the top
  right (stored via cookie).
- **Menu:** Navigation (Dashboard, Add record, Settings, Logs) sits behind the burger icon (☰) in the
  top left and opens as an overlay over the content. The pin icon in the menu lets you pin it - it then
  stays permanently visible and the content shifts to the right accordingly. The pin state is stored in
  the browser (`localStorage`) and only applies locally to this device/browser.
- **Timezone & date/time format:** By default the container runs in UTC. Under **Settings** you can
  choose a real IANA timezone (e.g. `Europe/Vienna`) as well as the display format for timestamps -
  this affects the logs (`/logs`) and the timestamps shown on the dashboard (e.g. "Last sync"). Changes
  take effect immediately, without a container restart. Alternatively set it via the `TZ` environment
  variable (see `.env.example`) - in that case it takes precedence and the field in Settings is
  disabled.

### HTTPS / secure connection

By default the Web UI is only served over plain HTTP (port 8080). Under **Settings -> HTTPS** you can
additionally turn on an encrypted connection on port 8443 (both ports keep working side by side - HTTP
isn't disabled) - `https://<host>:8443`. Two certificate sources are available:

- **Self-signed (default once enabled):** generated automatically, no setup needed. Since it isn't
  issued by a trusted certificate authority, browsers will show a security warning the first time you
  open the HTTPS URL - that's expected and can be confirmed/added as an exception. Optionally, a
  hostname or IP (e.g. your own DDNS domain) can be entered in Settings, which is then used as the
  certificate's name (CN/SAN) instead of a generic `localhost` certificate. A "Regenerate certificate"
  button is available if you ever need a fresh one.
- **Custom certificate:** import your own certificate + private key (PEM format, unencrypted, e.g. one
  issued by Let's Encrypt or an internal/company CA) to avoid the browser warning entirely. Once
  uploaded, the certificate source switches to "Custom certificate" automatically; it can be removed
  again at any time (reverting to the self-signed one).

Both the certificate and private key are stored in `config/certs/` (on the same persistent volume as
`config/config.json`), and every change takes effect immediately - no container restart required. The
HTTPS port itself can be changed via the `PORT_HTTPS` environment variable (default `8443`) if it needs
to be mapped to something else.

### Two-factor authentication (2FA)

Under **Settings -> Two-factor authentication (2FA)** you can add a second login step (TOTP, RFC 6238)
on top of the username/password - off by default.

- **Enable:** click "Enable 2FA", scan the shown QR code with an authenticator app (e.g. Google
  Authenticator, Aegis, 1Password, ...) - or enter the displayed key manually - then confirm with the
  current 6-digit code. Afterwards, a correct username/password no longer logs you in directly; a valid
  code from the app is also required (`/login/2fa`), with a tolerance of one 30-second step to allow for
  clock drift.
- **Recovery codes:** enabling 2FA (and every time you regenerate them) generates 8 single-use recovery
  codes, shown exactly once - store them somewhere safe (e.g. a password manager or printout). Each one
  can be used instead of the authenticator code, both to log in and to confirm disabling 2FA, and is
  consumed (invalidated) after use. "Regenerate recovery codes" under Settings invalidates all previous
  ones and issues a fresh set.
- **Disable:** requires a valid code (authenticator or recovery) as confirmation, same as changing other
  security-relevant settings.

The TOTP secret and the (hashed) recovery codes are stored in `config/config.json`, alongside the
existing Web UI credentials.

### Via the CLI (e.g. if you don't want a Web UI)

```bash
docker exec -it etf-multiddns python -m app.cli list
docker exec -it etf-multiddns python -m app.cli add --domain example.com --name home --type A --ttl 300
docker exec -it etf-multiddns python -m app.cli remove <record-id>
docker exec -it etf-multiddns python -m app.cli sync
```

## How it works

1. Every `CHECK_INTERVAL` seconds (default 300, minimum 60), the current public IPv4 (via
   `api.ipify.org`, with fallbacks) and/or IPv6 is determined - depending on whether A and/or AAAA
   records are configured.
2. For each active record, Domain Chief is checked to see whether a DNS record with a matching name +
   type already exists.
   - **None exists:** the record is newly created via the API (`POST /domains/{domain}/dns/records`).
   - **One exists, but with different content:** the record is updated
     (`PUT /domains/{domain}/dns/records/{id}`).
   - **Content already matches:** nothing happens (no unnecessary API call).
3. Rate limits (HTTP 429) from the Domain Chief API are respected (`Retry-After` header) and retried
   automatically with backoff.

## Security notes

- The Web UI is protected by login (see above, the setup wizard or `WEBUI_USERNAME` /
  `WEBUI_PASSWORD`). However, there is **no CSRF protection** and **no brute-force/rate-limit
  protection** for the login. It's still intended to primarily be reachable within your own (home)
  network - don't expose it unprotected directly to the internet. If external access is desired,
  put a reverse proxy with its own auth/SSO and rate limiting in front of it as well.
- HTTPS (see above) protects the connection itself (credentials/session cookie in transit) but doesn't
  replace a reverse proxy for internet-facing setups - the self-signed certificate in particular isn't
  trusted by browsers/clients out of the box. For anything beyond your own local network, prefer a
  reverse proxy with a certificate from a trusted CA (e.g. Let's Encrypt) in front of this container,
  or import that certificate directly under Settings -> HTTPS.
- The session cookie is signed with a key that is automatically generated on first start and
  permanently stored in `config/config.json` (`secret_key`). Anyone with write access to this file can
  forge valid sessions with it - the file should accordingly only be readable by the container itself.
- The password is not stored in plain text, but as a hash (`werkzeug.security`, scrypt). The same
  applies to 2FA recovery codes; the TOTP secret itself is stored as-is (it must be, to compute/verify
  codes), so `config/config.json` should be treated as sensitive either way.
- The API token is stored locally in `config/config.json` when set via the Web UI. If it's set via an
  environment variable instead, that takes precedence and the fields in the Web UI are disabled. The
  same applies analogously to the Web UI credentials and `WEBUI_USERNAME` / `WEBUI_PASSWORD`.

## Known limitations

- The Domain Chief API doesn't have a PATCH for records - an update replaces type, content, and TTL
  entirely (the client handles this correctly and automatically).
- Only A and AAAA records are actively managed by this tool as a "DDNS target". The API itself
  supports further types (CNAME, MX, TXT, ALIAS, CAA, SRV, TLSA, NS), which aren't needed here though.
- There is no test mode for the Domain Chief API - changes to real domains go live immediately. To
  experiment, Domain Chief offers free `.example` domains.
- The bot/abuse protection in front of `domain.chief.app` blocks requests using the `requests`
  library's default User-Agent (`python-requests/x.y`) with a plain text response `Bad Request` (not
  JSON, doesn't come from the Domain Chief API itself). The client therefore deliberately sets a
  different User-Agent (`curl/8.4.0`), which is demonstrably let through.

## Sources

- [Domain Chief - developer documentation](https://docs.chief.tools/domainchief/developers/build-with-domain-chief)
- [Domain Chief API reference (OpenAPI)](https://docs.chief.tools/api/domainchief)
- [Create a Personal Access Token](https://domain.chief.app/api/token/create)

---

An AI project, made by [EiTiFuzzi](https://github.com/EiTiFuzzi) with the help of [Claude](https://claude.com)
[![Claude](https://img.shields.io/badge/Claude-D97757?logo=claude&logoColor=fff)](https://claude.com)
