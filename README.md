# Honmaru（本丸）

The household keep: a self-hosted life dashboard + coach. Passive data in (Apple
Health, Michi, Kakeibo, Mishka Hub, calendar, weather) — one bridge to look at, one
gentle nudge pipe out, and a journal that writes itself.

**Status: docs-first planning complete (2026-07-10); implementation not started.**

Start here: [docs/PLAN.md](docs/PLAN.md) → [docs/HANDOFF.md](docs/HANDOFF.md) (open
questions, several blocking) → phase docs in [docs/phases/](docs/phases/).

Stack: Vite/React/TS/Tailwind v4 PWA + FastAPI/SQLite, GitHub Pages + Cloudflare
Tunnel + LaunchAgents — the fourth verse of the household pattern (Mishka Hub, Michi,
Kakeibo came first). Identity is Mishka Hub's; the palette is Aizome, mirrored not
forked; personal specifics live in gitignored `docs/PRIVATE.md` and the runtime DB,
never in this repo.
