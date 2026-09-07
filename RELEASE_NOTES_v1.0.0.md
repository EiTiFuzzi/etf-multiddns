# v1.0.0 - Initial release

ETF-MultiDDNS is a small self-hosted Docker container that keeps A/AAAA DNS records at
[Domain Chief](https://domain.chief.app) and/or [Cloudflare](https://www.cloudflare.com/) in sync with
your current public IP address - each record picks its own provider, so both can be used side by side
for different domains.

## Highlights

- **Two providers, one tool**: Domain Chief and Cloudflare are both optional and independent - mix and
  match per record.
- **Web UI**: sortable/filterable record table (Provider, Host, Type, Proxy Status, TTL, Current IP,
  Status, Last sync, Active), an on/off toggle switch per record, an "import existing records" flow for
  records already pointing at your public IP, and a Cloudflare-style Proxy Status column (Proxied /
  DNS only).
- **Security**: hashed Web UI login, optional two-factor authentication (TOTP, with recovery codes),
  and an optional self-signed (or your own) HTTPS listener alongside plain HTTP.
- **CLI**: manage records via `docker exec` for scripted/SSH-only setups, no Web UI required.
- **i18n**: full English and German UI.
- **Multi-arch Docker image**: `linux/amd64` and `linux/arm64`, published to
  `ghcr.io/eitifuzzi/etf-multiddns`.

## Getting started

```bash
docker run -d \
  --name etf-multiddns \
  --restart unless-stopped \
  -p 8080:8080 -p 8443:8443 \
  -v $(pwd)/config:/config \
  ghcr.io/eitifuzzi/etf-multiddns:latest
```

Then open `http://<host>:8080` and add your Domain Chief and/or Cloudflare API token under **Settings**.
See the [README](README.md) ([German version](LIESMICH.md)) for the full setup guide, required API
token scopes, and Docker Compose example.

## Security

A CVE audit of the pinned Python dependencies (checked live against the OSV database) and the custom
code found no known vulnerabilities - see [`CVE-AUDIT.md`](CVE-AUDIT.md) for the full report and
methodology.
