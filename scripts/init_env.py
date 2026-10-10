# copy .env.example to .env, fill dev secrets with random values
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
fills = {"POSTGRES_PASSWORD": secrets.token_hex(16), "JWT_SECRET": secrets.token_hex(32)}
lines = []
for line in (root / ".env.example").read_text().splitlines():
    key = line.split("=", 1)[0]
    lines.append(f"{key}={fills[key]}" if key in fills else line)
(root / ".env").write_text("\n".join(lines) + "\n")
print("created .env with random POSTGRES_PASSWORD and JWT_SECRET")
