# Security policy

OxeePhone is Oxeegen's self-hosted voice agent platform. It handles phone
calls, recordings, transcripts and the keys of your model and telephony
providers: we take its security seriously and thank everyone who helps keep
it safe.

## Supported versions

Security fixes are released in the latest OxeePhone version only. Keep your
servers up to date:

```bash
sudo /opt/oxeephone/brand/install.sh update
```

The running version is shown at the top of the sidebar, and the application
tells you when a new release is out. See the
[releases](https://github.com/Oxeegen/OxeePhone/releases) for what changed.

## Reporting a vulnerability

**Do not report vulnerabilities in public issues, discussions or pull
requests.** Report them privately through a
[GitHub security advisory](https://github.com/Oxeegen/OxeePhone/security/advisories/new).

Please include:

- the OxeePhone version and how it is deployed (`brand/install.sh`, Docker
  Compose…);
- the affected area (API route, screen, telephony, MCP server, installer…);
- the steps to reproduce, and what an attacker could do with it;
- logs or a proof of concept, **with every key, password and caller's
  personal data removed**.

We acknowledge the report, keep you informed while we work on a fix, and
credit you in the release notes if you wish once the fix is published.

## Scope

- **In scope**: the OxeePhone code (`api/brand/`, `ui/src/brand/`, `brand/`,
  the installer) and the Dograh and Pipecat code as shipped in OxeePhone.
- **Upstream**: a vulnerability that also affects
  [Dograh](https://github.com/dograh-hq/dograh) or
  [Pipecat](https://github.com/pipecat-ai/pipecat) should be reported to them
  as well; tell us, and we will follow up in OxeePhone.
- **Out of scope**: your own model servers, telephony provider or PBX, and
  configurations that publish secrets (for example a `.env` file exposed by a
  web server).

## Running OxeePhone safely

- Keep `.env` private: it holds the generated secrets and your provider keys.
- Serve OxeePhone over HTTPS (the installer generates a certificate); do not
  expose its database, Redis or MinIO ports to the internet.
- Create one API key per integration or AI agent, and revoke the ones you no
  longer use (Developers › API keys). Publishing from the MCP server stays off
  unless `OXEE_MCP_CAN_PUBLISH` is set.
- Test campaigns simulate tools by default; use "real" tools only against
  systems that may receive test calls.
