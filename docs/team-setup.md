# Admin: how to connect a team

An API key is a person's name plus the owner graphs (`projects`) they may use. A project is one owner graph. `OWNER_SCOPE=client` (the default) does not use keys.

**Threat model.** In token mode the server sets `created_by` and `updated_by` on every write from the key name; the server administrator is trusted. That holds only when the admin is the only one with access to the server process, the keys file, `.env`, and the database; the database port is closed; and clients reach the server over HTTPS. `client` and `header` take those fields from `metadata.created_by` and `metadata.updated_by` instead.

1. Put `OWNER_SCOPE=token`, `ADMIN_TOKEN`, and `API_KEYS_FILE` in `.env`. The server refuses to start in token mode if the token is empty or the keys file is missing. Example compose fragment:

   ```yaml
   environment:
     OWNER_SCOPE: token
     ADMIN_TOKEN: ${ADMIN_TOKEN}
     API_KEYS_FILE: /run/keys.json
   volumes:
     - ./keys.json:/run/keys.json:ro
   ```

2. Create one key per person. The raw key is printed once and is not stored.

   ```bash
   uv run graph-memory-mcp keys create --name alice --projects p1,p2
   uv run graph-memory-mcp keys list
   ```

3. Give each person the Bearer key and the project ids they may use. They send `Authorization: Bearer <key>` on `/mcp`. `owner_id` must be one of those projects; omit it to use the first.

4. Change access with `keys set-projects <id> p1,p3`. Revoke with `keys revoke <id>`. A revoked or unknown key is HTTP 401.

5. Close the database port, keep `keys.json` mode `0600`, and terminate TLS in front of the process. A `:ro` mount of a mode `0600` file is readable only when the container user's UID matches the file owner. `/admin` always needs `ADMIN_TOKEN` in this mode. `/metrics` stays open.
