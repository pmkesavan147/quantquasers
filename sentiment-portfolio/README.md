# Ledger — Sentiment-Based Portfolio Creator (Frontend)

Frontend-only fintech dashboard: onboarding survey → trader persona → sentiment-tilted
portfolio allocation → sentiment drill-down → rebalance history. No backend, no real
LLM calls, no real market data — everything "AI" is mocked, but the allocation math
is real and recalculates live.

## Run it

```bash
npm install
npm run dev
```

Build for production:

```bash
npm run build
npm run preview
```

## How it's wired

- **Flow**: `/` (onboarding wizard) → `/persona` (reveal) → `/dashboard`, `/insights`,
  `/history` (shared nav shell).
- **State**: `src/lib/store.tsx` — a single context holding persona, sentiment, and
  the computed allocation breakdown. All pages read/write through `useStore()`.
- **Mocked "AI"**: `src/services/mockApi.ts` — `classifyPersona`, `extractPersonalSentiment`,
  `fetchMarketSentiment`, `fetchRebalanceHistory`. These return data matching the schemas
  in `src/types/index.ts`. **Swap these function bodies for real fetch() calls** to your
  backend/LLM later — nothing else needs to change since every page consumes the same shapes.
- **Real allocation math**: `src/lib/allocation.ts` — deterministic baseline weights per
  persona, capped market/conviction tilts, clamped to non-negative and renormalized to
  100%. This actually recomputes whenever sentiment is refreshed or re-extracted.
- **Theme**: `src/lib/theme.tsx` toggles a `dark`/`light` class on `<html>`. Tailwind's
  `light:` variant (custom, added in `tailwind.config.js`) is used for light-mode overrides.

## Design notes

Dark-by-default trading-terminal aesthetic: near-black slate background, amber (`#ffb648`)
for tilt-up/positive, red-pink (`#ff5470`) for tilt-down/negative — a single accent pairing
kept consistent across every chart, badge, and delta tag. Space Grotesk for display type,
Inter for body copy, IBM Plex Mono for all numbers/data so figures feel like terminal ticks.

## Next steps (backend integration)

1. Replace the bodies of the four functions in `mockApi.ts` with real API calls.
2. Keep the same return shapes (`Persona`, `MarketSentimentItem`, `PersonalSentiment`,
   `RebalanceEvent`) so no component code needs to change.
3. `computeAllocation()` in `allocation.ts` can stay client-side, or move server-side —
   the interface (`persona`, `marketItems`, `personal` in → `breakdown` out) stays the same.
