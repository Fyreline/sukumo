# Sukumo（蒅）

Sukumo is the fermented indigo leaf every aizome dye vat starts from — and this app
is the household's: a self-hosted life dashboard + coach. The raw leaves of ordinary
days go in passively (Apple Health, Michi, Kakeibo, Mishka Hub, calendar, weather);
out come one bridge worth opening every morning, one gentle nudge pipe to the phone,
and a journal that ferments itself.

**Status: docs-first planning complete (2026-07-10); implementation not started.**

Start here: [docs/PLAN.md](docs/PLAN.md) → [docs/HANDOFF.md](docs/HANDOFF.md) (open
questions, several blocking) → phase docs in [docs/phases/](docs/phases/).

Stack: Vite/React/TS/Tailwind v4 PWA + FastAPI/SQLite, GitHub Pages + Cloudflare
Tunnel + LaunchAgents — the fourth verse of the household pattern (Mishka Hub, Michi,
Kakeibo came first). Identity is Mishka Hub's; the palette is Aizome, mirrored not
forked; personal specifics live in gitignored `docs/PRIVATE.md` and the runtime DB,
never in this repo.
