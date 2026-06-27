# WeChat History on macOS

Mac wrapper for reading WeChat 4.x local chat history. It borrows the workflow
from `HelloKuoty/wechat_history`, but replaces the Windows-only `Weixin.exe`
path and key scanner with a macOS flow based on
`ylytdeng/wechat-decrypt`.

## What This Does

- Detects the local WeChat 4.x data directory.
- Installs the upstream decrypt/export tools under `tools/wechat-decrypt`.
- Compiles the macOS memory key scanner.
- Writes `tools/wechat-decrypt/config.json` for this machine.
- Runs decrypt, export, or local web UI commands from one wrapper.

Sensitive outputs are ignored by git:

- `tools/wechat-decrypt/`
- `all_keys.json`
- `decrypted/`
- `exported_chats/`
- `exports/`
- `output/`

## Current Machine

Detected on this Mac:

- WeChat app: `/Applications/WeChat.app`
- WeChat version: `4.1.10`
- Data root:
  `~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files`
- Selected database directory:
  `~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/zeng540125485_3c73/db_storage`

The raw WeChat databases are encrypted. `sqlite3` cannot open
`message/message_0.db` directly, so key scanning and decryption are still
required.

## Commands

Check the local environment:

```bash
python3 wechat_history_mac.py doctor
```

Install the tools and compile the scanner:

```bash
scripts/bootstrap_macos.sh
```

If `python3` is still the system Python 3.9, the script will use the bundled
Codex Python 3.12 on this machine automatically.

## Decrypt

macOS blocks process memory reads for apps signed with Hardened Runtime. This
machine currently has WeChat signed with `flags=0x10000(runtime)`, so the key
scanner cannot work until WeChat is re-signed locally.

Run this once before scanning keys:

```bash
killall WeChat
sudo codesign --force --deep --sign - /Applications/WeChat.app
open /Applications/WeChat.app
```

After WeChat opens, log in and open several chats so keys are resident in
memory. Then run:

```bash
python3 wechat_history_mac.py decrypt
```

This creates decrypted SQLite databases under:

```text
tools/wechat-decrypt/decrypted/
```

## View Or Export

Start the local web UI:

```bash
python3 wechat_history_mac.py serve
```

Export chats:

```bash
python3 wechat_history_mac.py export exports
```

## Notes

- Do not commit decrypted databases, keys, or exports.
- If you switch WeChat accounts, run `doctor` again and verify the selected
  `db_storage` path.
- If WeChat updates, macOS may restore the original signature. Re-run the
  `codesign` step before scanning keys again.
