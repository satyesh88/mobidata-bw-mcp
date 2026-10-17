# Updating the hosted services

How to ship new code to a server that runs the MCP server and, optionally, the Telegram bot as systemd
services (see [README.md](README.md) for the first install). Placeholders: `<SSH_ALIAS>` is your SSH
host alias, `<DOMAIN>` the public host name. Never put real addresses, host names, keys or tokens in
this repository or in chat.

## Layout on the server

| Item | Location |
| --- | --- |
| Code (a Git checkout, root-owned) | `/opt/mobidata-bw-mcp` |
| MCP venv, third-party packages only | `/opt/mobidata-bw-mcp/venv` |
| Bot venv, third-party packages only | `/opt/mobidata-bw-mcp/venv-bot` |
| MCP config and API keys | `/etc/mobidata-mcp/env`, `/etc/mobidata-mcp/keys` |
| Bot secrets | `/etc/mobidata-bot/env` |
| Services | `mobidata-mcp` (127.0.0.1:8765), `mobidata-bot` (no listening port) |

What differs per service decides what an update needs:

| Service | Runs from | After `git pull` you need |
| --- | --- | --- |
| `mobidata-bot` | `src/` in the checkout (`PYTHONPATH`) | a restart only |
| `mobidata-mcp` | `src/` in the checkout (`PYTHONPATH`, Python module entry point) | a restart only |

## Stale-wheel lesson and one-time migration

A checkout at a new commit does not prove the service runs that commit. The server once
loaded an old wheel from site-packages while the checkout contained the departures fixes.
A restart kept loading that wheel. Both services now use the checkout as the only source
of application code; their venvs retain third-party dependencies only.

Run this migration once before removing the installed application package. The updated
MCP unit uses both PYTHONPATH and `python -m mobidata_bw_mcp.server`, so uninstalling the
wheel cannot remove its entry point. Confirm the loaded unit and import path first:

```bash
set -e
cd /opt/mobidata-bw-mcp
git pull --ff-only origin main
sudo install -m 644 deploy/mobidata-mcp.service /etc/systemd/system/mobidata-mcp.service
sudo systemctl daemon-reload
sudo systemctl show mobidata-mcp -p Environment --value | tr ' ' '\n' \
  | grep -Fx 'PYTHONPATH=/opt/mobidata-bw-mcp/src'
sudo systemctl show mobidata-mcp -p ExecStart --value \
  | grep -F 'python -m mobidata_bw_mcp.server'
PYTHONPATH=/opt/mobidata-bw-mcp/src venv/bin/python -B -c \
  'import mobidata_bw_mcp.server as s; assert s.__file__ == "/opt/mobidata-bw-mcp/src/mobidata_bw_mcp/server.py"'
venv/bin/python -m pip uninstall -y mobidata-bw-mcp
sudo systemctl restart mobidata-mcp
sudo systemctl restart mobidata-bot
```

Do not reinstall the project wheel during routine updates. Install dependency requirements
when they change. Never restart another site's service as part of this procedure.
At startup both services log `startup service=... commit=<git hash> source=...`.
Compare that commit with `git rev-parse --short=12 HEAD` in the checkout:

```bash
journalctl -u mobidata-mcp -u mobidata-bot --since "10 minutes ago" --no-pager \
  | grep 'startup service='
```

## One-time setup: read-only deploy key

The server pulls over SSH with a read-only deploy key, so the repository can stay private.

1. On the server: `ssh-keygen -t ed25519 -f /root/.ssh/mobidata_deploy -N "" -C "deploy"`, then print the
   public half with `cat /root/.ssh/mobidata_deploy.pub`. Never print the file without `.pub`.
2. On GitHub: repository, Settings, Deploy keys, Add deploy key. Paste the public line and leave
   "Allow write access" unchecked. A key can be a deploy key for one repository only.
3. On the server, append (do not overwrite) to `/root/.ssh/config`:
   ```
   Host github-mobidata
       HostName github.com
       User git
       IdentityFile /root/.ssh/mobidata_deploy
       IdentitiesOnly yes
   ```
4. Test and switch the remote:
   ```
   ssh -T git@github-mobidata
   cd /opt/mobidata-bw-mcp
   git remote set-url origin git@github-mobidata:<OWNER>/mobidata-bw-mcp.git
   git ls-remote origin HEAD
   ```
5. To revoke access, delete the deploy key on GitHub.

Without a deploy key, ship a bundle instead (see "No credentials on the server" below).

## Routine update

### 1. Before touching the server (on your machine)

```bash
uv run ruff check . && uv run --extra telegram pytest -q
git push origin main
git rev-parse --short HEAD          # the commit the server should end up on
```

If the change adds or updates dependencies, refresh the locked files and commit them too:

```bash
uv lock
uv export --frozen --no-dev --no-emit-project --no-header -o deploy/requirements.txt
uv export --frozen --no-dev --no-emit-project --no-header --extra telegram -o deploy/requirements-bot.txt
```

### 2. Check other sites on the host

The server may host other sites. Note their status codes first and compare them after every step. An
update must never change them.

### 3. Bot only

```bash
set -e
cd /opt/mobidata-bw-mcp
git pull --ff-only
test "$(git rev-parse --short HEAD)" = <EXPECTED_COMMIT>
systemctl restart mobidata-bot
sleep 8
systemctl is-active mobidata-bot mobidata-mcp
journalctl -u mobidata-bot -n 15 --no-pager
```

Expect `ready tools=17` and `Application started`. If `deploy/requirements-bot.txt` changed, run this
before the restart:

```bash
venv-bot/bin/pip install --quiet --only-binary=:all: --require-hashes -r deploy/requirements-bot.txt
```

### 4. MCP server

```bash
set -e
cd /opt/mobidata-bw-mcp
OLD=$(git rev-parse --short HEAD)
git pull --ff-only
git diff --stat "$OLD"..HEAD -- deploy/requirements.txt deploy/mobidata-mcp.service
# Complete the one-time source-only migration above before this routine update.
# Only if deploy/requirements.txt changed:
#   venv/bin/pip install --quiet --only-binary=:all: --require-hashes -r deploy/requirements.txt
# Only if the unit file changed:
#   install -m 644 deploy/mobidata-mcp.service /etc/systemd/system/ && systemctl daemon-reload
systemctl restart mobidata-mcp
sleep 5
curl -fsS http://127.0.0.1:8765/health
systemctl is-active mobidata-mcp mobidata-bot
```

After a restart the MCP server rebuilds the traffic-sign index in the background (about a minute, up to
roughly 700 MB, inside its 1 GB cap). `/health` answers at once; the first sign-related request waits.
Restart the MCP server before the bot when both change.

### 5. Verify

- The services are `active`, `/health` returns `{"status": "ok"}`, and the other sites are unchanged.
- Public check: `GET https://<DOMAIN>/health` is 200, `POST https://<DOMAIN>/mcp` without a key is 401.
- Look at the journal with secrets masked:
  ```bash
  journalctl -u mobidata-bot -n 30 --no-pager | sed -E \
    's/[0-9]{8,}:[A-Za-z0-9_-]{25,}/<token>/g; s/sk-ant-[A-Za-z0-9_-]+/<anthropic>/g; s/mdbw_[A-Za-z0-9_-]+/<mcp-key>/g'
  ```

### Use hard stops

Write each command on its own line under `set -e`. A chain such as `git pull && echo ok` does not stop
the script when the pull fails, and the restart still runs. The checkout must be clean (`git status
--short` prints nothing) because the pull is fast-forward only.

## Changing configuration or secrets

- Edit `/etc/mobidata-mcp/env` or `/etc/mobidata-bot/env` yourself in an SSH session, then restart the
  service. Do not paste values into chat, tickets or Git.
- systemd `EnvironmentFile` lines are plain `KEY=value`: no spaces around `=` and no trailing `# comment`.
- Keys for the MCP server: `python3 deploy/new-api-key.py <NAME> --owner mobidata-mcp` prints the key once;
  delete its line in `/etc/mobidata-mcp/keys` to revoke it. No restart is needed.
- The bot keeps conversations, rate limits and the daily budget in memory, so a restart resets them.

## Roll back

On the server checkout there are no local changes, so it can move to any earlier commit:

```bash
set -e
cd /opt/mobidata-bw-mcp
git reset --hard <PREVIOUS_COMMIT>
# The source-only units load this checkout on restart.
systemctl restart mobidata-mcp      # or mobidata-bot
```

If a dependency changed in the bad release, also reinstall the matching requirements file from the
previous commit. Afterwards `git pull --ff-only` brings the server forward again once a fix is pushed.

## No credentials on the server (bundle)

On your machine:

```bash
git bundle create /tmp/update.bundle <SERVER_COMMIT>..main
scp /tmp/update.bundle <SSH_ALIAS>:/tmp/
```

On the server, replace the `git pull` line of the procedures above with:

```bash
git pull --ff-only /tmp/update.bundle main
rm /tmp/update.bundle
```

`<SERVER_COMMIT>` is the commit the server is on (`git rev-parse --short HEAD` there).
For a bot-only update, pull the pushed commit and restart only `mobidata-bot`, as in
section 3. For changes affecting both services, follow the MCP update procedure and
restart `mobidata-mcp` before `mobidata-bot`.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `could not read Username for 'https://github.com'` | The remote is still HTTPS. Use the deploy key setup above. |
| `Permission denied (publickey)` | The deploy key is not added on GitHub, or the `IdentityFile` path is wrong. |
| Bot log shows `409 Conflict` | A second copy of the bot is polling with the same token. Stop it (for example the one on a laptop). |
| MCP returns 421 `Invalid Host header` | `MOBIDATA_MCP_ALLOWED_HOSTS` in `/etc/mobidata-mcp/env` does not list the public host name. |
| Service killed shortly after start | Memory cap reached. Check `systemctl show <unit> -p MemoryPeak`; the MCP cap is 1 GB, the bot's 600 MB. |
| `pip` wants to compile something | Stop. A package has no wheel for this Python. Do not install build tools on a shared host. |
