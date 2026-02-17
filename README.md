# Claude Code Remote

Use Claude Code from your phone — or anywhere — over a secure VPN connection.

![Architecture](architecture.svg)

## What This Is

A set of scripts that give you full interactive Claude Code CLI access from your phone's browser. It uses [Tailscale](https://tailscale.com) to create a secure encrypted tunnel between your devices, [ttyd](https://github.com/tsl0922/ttyd) to serve your terminal as a web page, [tmux](https://github.com/tmux/tmux) to keep sessions alive across disconnects, and a FastAPI voice wrapper that adds a mobile-friendly UI with iOS dictation support and quick-action buttons. Everything binds exclusively to your Tailscale IP — nothing is exposed to the public internet. Works from anywhere, not just your home WiFi, as long as your Mac is awake.

## Cost

This entire setup is free. Every tool used is either open-source or has a free tier:

| Tool | Cost |
|------|------|
| [Tailscale](https://tailscale.com/pricing) | Free for personal use (up to 3 users, 100 devices). Paid plans start at $6/user/month for teams. |
| [ttyd](https://github.com/tsl0922/ttyd) | Free and open-source |
| [tmux](https://github.com/tmux/tmux) | Free and open-source |
| [FastAPI](https://fastapi.tiangolo.com) + [Uvicorn](https://www.uvicorn.org) | Free and open-source |
| Claude Code CLI | Requires an [Anthropic API plan](https://www.anthropic.com/pricing) (usage-based) |

The only ongoing cost is your existing Claude Code API usage — the remote access layer itself adds nothing.

## Prerequisites

- macOS (Apple Silicon or Intel)
- [Homebrew](https://brew.sh)
- [Tailscale](https://tailscale.com) account + app installed on Mac and phone (free personal plan works)
- Python 3.9+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated

## Step-by-Step Setup

### 1. Install dependencies

```bash
brew install ttyd tmux
pip3 install fastapi uvicorn
```

### 2. Set up Tailscale

- Install Tailscale on your Mac and phone
- Sign in on both devices with the same account
- Verify they can see each other:

```bash
tailscale ip -4
```

This prints your Mac's Tailscale IP (like `100.x.y.z`). Save this — you'll need it.

### 3. Clone this repo

```bash
git clone https://github.com/buckle42/claude-code-remote.git
cd claude-code-remote
```

### 4. Test it

Start everything:

```bash
./scripts/start-remote-cli.sh
```

You should see output like:

```
Tailscale IP: 100.x.y.z
caffeinate running (PID: 12345)
ttyd running (PID: 12346) on http://100.x.y.z:7681
voice wrapper running (PID: 12347) on http://100.x.y.z:8080

=== Remote CLI Ready ===
Terminal:  http://100.x.y.z:7681
Voice UI:  http://100.x.y.z:8080
```

On your phone (with Tailscale active), open the Voice UI URL in your browser. You should see a terminal with Claude Code ready to go.

To stop:

```bash
./scripts/stop-remote-cli.sh
```

### 5. Set up auto-start (optional)

If you want everything to start automatically when your Mac boots:

1. Edit `scripts/remote-cli.plist` — replace every `YOUR_USERNAME` with your macOS username
2. Copy scripts to a location outside `~/Documents/` (macOS restricts launchd access to `~/Documents/` due to TCC):

```bash
mkdir -p ~/.local/bin/remote-cli
cp scripts/* ~/.local/bin/remote-cli/
chmod +x ~/.local/bin/remote-cli/*.sh
```

3. Install the launch agent:

```bash
cp scripts/remote-cli.plist ~/Library/LaunchAgents/com.user.remote-cli.plist
launchctl load ~/Library/LaunchAgents/com.user.remote-cli.plist
```

To unload later:

```bash
launchctl unload ~/Library/LaunchAgents/com.user.remote-cli.plist
```

## Usage Tips

| Action | How |
|--------|-----|
| **Voice dictation** | Use the text input field at the bottom of the Voice UI — iOS dictation works natively there. Avoid dictating directly into the terminal (the raw xterm.js terminal duplicates text due to IME handling). |
| **Quick keys** | The button bar gives you tap targets for arrow keys, Tab, Esc, Ctrl+C, Enter, and Clear — keys that are hard to hit on a phone keyboard. |
| **Switch to your desktop** | Open any terminal on your Mac and run `tmux attach -t claude` to pick up the exact same session you were using on your phone. Both screens mirror each other. |
| **Resume on your phone** | Hit the **Resume** button in the Voice UI to reconnect to a previous Claude Code conversation. |
| **New session** | Hit the **New** button to exit the current Claude session and start a fresh one. |
| **Copy output** | Hit **Copy** to capture the terminal scrollback into a text area you can select and copy from. |
| **Auto-reconnect** | When your phone wakes from sleep, the terminal iframe reloads automatically. No manual refresh needed. |

## Security

All services bind exclusively to the Tailscale interface IP — they are unreachable from the public internet and from your local network. Tailscale creates a peer-to-peer [WireGuard](https://www.wireguard.com/) encrypted tunnel between your devices, and every device on your tailnet must be authenticated via SSO. No ports are forwarded or exposed publicly.

**Trade-off to be aware of:** This setup gives full terminal access to your Mac. Anyone with access to your Tailscale account could interact with your shell. If you want to limit access to just Claude Code (no raw shell), see the Future Ideas section below.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| ttyd won't start | Check if port 7681 is already in use: `lsof -i :7681` |
| Can't connect from phone | Verify Tailscale is active on both devices: `tailscale status` |
| Voice dictation duplicates text | Use the Voice Wrapper UI (`:8080`), not the raw terminal (`:7681`) |
| launchd can't access ~/Documents/ | Copy scripts to `~/.local/bin/remote-cli/` (outside TCC-protected paths) |
| Claude Code env vars conflict | The `tmux-attach.sh` wrapper handles this automatically by unsetting them |
| Connection drops when phone sleeps | Just reopen the page — auto-reconnect reloads the terminal |

## How It Works

**Tailscale** creates an encrypted peer-to-peer tunnel between your phone and Mac using the WireGuard protocol. It requires zero network configuration — no port forwarding, no dynamic DNS, no firewall rules. The free tier covers personal use.

**ttyd** turns any terminal command into a web page served over HTTP and WebSocket. In this setup, it serves a tmux session so you get a full interactive terminal in your phone's browser.

**tmux** is a terminal multiplexer that keeps your Claude Code session alive even when you disconnect. Close your browser, lose your connection, or switch devices — reconnect anytime and pick up exactly where you left off.

**Voice Wrapper** is a FastAPI app that wraps the ttyd terminal in a mobile-friendly page. It adds a native text input field (where iOS dictation works properly), quick-action buttons for common keys, and auto-reconnect logic so the terminal reloads when your phone wakes from sleep.

**caffeinate** is a macOS utility that prevents your Mac from sleeping while the services are running, so they stay available when you're away from your desk.

**launchd** is the macOS service manager that can auto-start everything on boot and restart services if they crash. The included plist file handles this.

## Future Ideas

- Custom web chat UI wrapping `claude --output-format stream-json` (no raw terminal exposure)
- Voice assistant mode with Web Speech API for true hands-free operation
- Status dashboard showing active sessions and resource usage
