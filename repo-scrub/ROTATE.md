# Rotating leaked secrets

Rewriting history doesn't un-leak a secret: once pushed, it may already sit in forks, clones, PR diffs, CI logs, or scrapers. Rotation is the fix; the rewrite is cleanup. This covers every selected secret, and honestly every *kept* one that was ever live.

| Type | Rotate |
|---|---|
| Cloud keys (AWS/GCP/Azure) | deactivate/delete in the console or CLI, issue a new key, update every consumer (CI secrets, deploy config, local `.env`) |
| API tokens (GitHub PAT, Stripe, SaaS) | revoke in the issuer's dashboard, generate a replacement, redistribute |
| Private keys / certs (SSH, TLS, signing) | revoke/reissue the cert, new key pair, redeploy to every host that trusted the old one |
| DB passwords / connection strings | rotate at the database, update every connection string, bounce pools |
| Webhook URLs with embedded tokens | regenerate in the source app, update whatever posts to it |
