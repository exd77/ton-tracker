# TON New Token Tracker

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![TON](https://img.shields.io/badge/TON-Blockchain-0098EA?logo=ton&logoColor=white)](https://ton.org/)
[![DeDust](https://img.shields.io/badge/Data-DeDust%20%2B%20x1000-orange)](https://dedust.io/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Telegram bot for tracking newly launched TON tokens from DeDust/x1000 and sending rich launch alerts with token image, socials, deployer wallet, TON balance, launch stats, and bonding-curve progress.

> ⚠️ This tracker is informational only. It is not financial advice. Always DYOR.

## Preview

When a new token launch is detected, the bot sends a Telegram photo/message like this:

```text
$SHITON just launched on TON

Shit on TON
EQBv-VyGka2eKTau7x2AV1ipcTzGEsF4NE2Zbfl4sP1Uq...

📖 Description
┃ From $SHIT to $SHITON. Same smell, new chain.

🎒 Socials
┣ 💬 Telegram
┣ 🐦 X
┗ 🌐 Website

👤 Deployer
┣ Wallet: 0:01a7...e1c5
┣ Full: 0:01a7a7a7a618a662258b61a1c292c3b396ca64f3f6d9539612e55ac908e1e1c5
┣ Balance: 12.34 TON
┣ Deploy Amount: 4.85 TON
┗ Dev Buy: Unknown

📊 Launch Stats
┣ Raised: 4.85 / 1050 TON
┣ Bonded: 0.46%
┣ Holders: 10
┣ Age: 44s
┣ Market Cap: $901
┗ Volume 24h: $12.53

▰▱▱▱▱▱▱▱▱▱ 0.46%

🟧 Open x1000 Chart
🔎 DeDust Pool
🧭 Tonviewer

⚠️ Tracker Note
Automated alert, not financial advice. Always DYOR.
```

## Features

- **New launch detection** from DeDust TON pools.
- **x1000/DeDust enrichment** from the public DeDust coins API used by `x1000.finance/launches`.
- **Token image support** from x1000, TonAPI, or DeDust metadata.
- **Social link extraction** from token metadata and description URLs.
- **Deployer wallet detection** from x1000/DeDust `memecoin_extra_details.author`, with TonAPI admin fallback.
- **Deployer TON balance** via TonAPI account lookup.
- **Bonding curve progress bar** from `curve_ton_collected / curve_ton_max`.
- **Clickable links** to x1000, DeDust pool, and Tonviewer.
- **Safe Telegram HTML formatting** with escaped user/token-provided text.
- **No spam first run**: existing pools are baselined by default.

## Data Sources

- DeDust app: <https://dedust.io/>
- DeDust pools: `https://api.dedust.io/v2/pools`
- x1000 / DeDust coins API: `https://mainnet.api.dedust.io/v4/api/coins`
- TonAPI: `https://tonapi.io/v2`
- x1000 terminal: <https://x1000.finance/>

## Requirements

- Python 3.11+
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Telegram chat/channel/group ID
- Optional: TonAPI key for higher rate limits

## Quickstart

### 1. Clone

```bash
git clone https://github.com/exd77/ton-new-token-tracker.git
cd ton-new-token-tracker
```

### 2. Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
nano .env
```

Minimum required values:

```env
TELEGRAM_BOT_TOKEN=123456:your_botfather_token
TELEGRAM_CHAT_ID=your_chat_id_or_channel_username
```

If you send alerts to a Telegram channel, add the bot as a channel admin first.

### 4. Test without sending Telegram alerts

```bash
python tracker.py --dry-run
```

### 5. Run once

```bash
python tracker.py --once
```

### 6. Run continuously

```bash
python tracker.py
```

## Configuration

All configuration is done through `.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | required | Telegram bot token from BotFather. |
| `TELEGRAM_CHAT_ID` | required | Destination chat ID or channel username. |
| `POLL_INTERVAL_SECONDS` | `60` | Polling interval. |
| `SKIP_EXISTING_ON_FIRST_RUN` | `true` | Baseline existing pools on first run to avoid spam. |
| `REQUIRE_NATIVE_TON` | `true` | Only alert pools paired with native TON. |
| `TONAPI_KEY` | empty | Optional TonAPI bearer token. |
| `DEDUST_POOLS_URL` | `https://api.dedust.io/v2/pools` | DeDust pools endpoint. |
| `TONAPI_BASE_URL` | `https://tonapi.io/v2` | TonAPI base URL. |
| `X1000_ENABLED` | `true` | Enable x1000/DeDust launch enrichment. |
| `X1000_API_URL` | `https://mainnet.api.dedust.io/v4/api/coins` | DeDust coins API endpoint. |
| `X1000_BASE_URL` | `https://x1000.finance` | Fallback x1000 terminal link. |
| `X1000_TOKEN_ROUTE_PATTERN` | empty | Optional token-specific x1000 route pattern. |
| `PROGRESS_BAR_LENGTH` | `10` | Bonding progress bar length. |
| `DESCRIPTION_MAX_CHARS` | `300` | Max description length in alerts. |
| `MAX_SOCIAL_LINKS` | `5` | Max social links shown. |
| `MIN_TON_RESERVES` | `0` | Minimum native-TON reserves (in TON) for a pool to qualify. `0` disables the filter. |
| `TONAPI_CACHE_TTL_SECONDS` | `3600` | TTL for TonAPI jetton metadata cache. |
| `BALANCE_CACHE_TTL_SECONDS` | `60` | TTL for TonAPI account balance cache. |
| `X1000_CACHE_TTL_SECONDS` | `30` | TTL for x1000 coin list cache (shared by all pools in a tick). |
| `HTTP_RETRIES` | `3` | Auto-retry count on 429/5xx responses (TonAPI, Telegram). `0` disables. |
| `HTTP_BACKOFF_FACTOR` | `1.0` | Exponential backoff factor for retries. `1.0` → 1s, 2s, 4s. |
| `STATE_FILE` | `./state/seen_pools.json` | Local seen-pool state path. |

## Optional x1000 chart route

The bot always includes an `Open x1000 Chart` link. By default it points to:

```text
https://x1000.finance/
```

If you know the valid token-specific x1000 route, set:

```env
X1000_TOKEN_ROUTE_PATTERN=/tokens/{jetton_address}
```

Supported placeholders:

- `{asset}` — raw x1000 asset ID, if available.
- `{address}`, `{jetton_addr}`, `{jetton_address}` — jetton master address.

If the pattern cannot be formatted, the bot falls back to `X1000_BASE_URL`.

## Docker

```bash
docker build -t ton-new-token-tracker .
docker run --env-file .env -v "$PWD/state:/app/state" ton-new-token-tracker
```

## systemd

A sample service file is included:

```bash
sudo cp ton-launch-tracker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ton-launch-tracker
sudo journalctl -u ton-launch-tracker -f
```

If you install the project outside `/root/ton-launch-tracker`, update `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` in `ton-launch-tracker.service`.

## How detection works

1. Bot polls DeDust pools.
2. A pool is considered a launch candidate if it contains a jetton asset.
3. By default, the pool must include native TON.
4. Bot checks `state/seen_pools.json` to avoid duplicate alerts.
5. On first run, existing pools are marked as seen if `SKIP_EXISTING_ON_FIRST_RUN=true`.
6. For each new pool, bot enriches data from TonAPI and x1000/DeDust coins API.
7. Bot sends a Telegram alert with image and formatted launch details.

## Safety and secrets

Do **not** commit:

- `.env`
- Telegram bot token
- TonAPI key
- local state files
- logs or cache files

This repository includes `.env.example` only.

## Troubleshooting

### Bot sends nothing on first run

This is expected when:

```env
SKIP_EXISTING_ON_FIRST_RUN=true
```

The bot baselines existing pools first, then alerts only new pools.

### Telegram channel does not receive alerts

Check that:

- bot is added to the channel;
- bot is an admin;
- `TELEGRAM_CHAT_ID` is correct, e.g. `@yourchannel` or numeric chat ID.

### TonAPI rate limit

Add a TonAPI key:

```env
TONAPI_KEY=your_tonapi_key
```

### x1000 enrichment missing

The bot still sends a minimal alert if x1000/DeDust enrichment fails. Check logs and verify:

```env
X1000_ENABLED=true
X1000_API_URL=https://mainnet.api.dedust.io/v4/api/coins
```

## Development checks

```bash
python -m py_compile tracker.py
TELEGRAM_BOT_TOKEN='999999:TEST' TELEGRAM_CHAT_ID='0' python tracker.py --dry-run
```


## License

MIT
