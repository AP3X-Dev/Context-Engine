# ONI Design System Redesign — Landing Pages

Approved design for updating `oni.bot` and `cortex.oni.bot` landing pages to match the ONI Design System. Page structure, middleware routing, component file organization, and all content/copy remain unchanged.

## Color System

Replace all indigo/purple accent (`#6366f1`) with green (`#00d46a`).

### CSS Custom Properties

| Variable | Value |
|---|---|
| `--bg` | `#0a0a0a` |
| `--surface` | `#111111` |
| `--surface2` | `#1a1a1a` |
| `--border` | `rgba(255,255,255,0.08)` |
| `--text` | `#ffffff` |
| `--text2` | `#a0a0a0` |

Additional vars: accent glow, depth shadows, and purple/gold/cyan semantic colors.

## Typography

Swap Geist fonts for the ONI type stack:

| Role | Font | Details |
|---|---|---|
| Headings | Inter Tight 800 | tracking `-0.04em` |
| Body | DM Sans | 15-18px, line-height 1.6 |
| Code | JetBrains Mono | — |

- **Hero headlines:** `clamp(40px, 7vw, 78px)`, Inter Tight 800
- **Section titles:** `clamp(28px, 4vw, 44px)`, Inter Tight 800

## Component Updates

All existing components receive visual updates; no structural changes.

- **Nav** — Glassmorphism backdrop with scroll-state detection, logo icon with gradient, 60px height.
- **Buttons** — Green primary with depth shadows + elastic lift (`translateY(-8px)`); white-glow secondary; ghost style unchanged.
- **Cards** — Gradient surface (`#1a1a1c` to `#111113`), shimmer sweep `::before` on hover, green glow border, icon containers with pulse animation.
- **Pricing cards** — Same card treatment as above; highlighted tier gets green accent border + glow.
- **Footer** — Gradient `border-image`, updated spacing.
- **Hero sections** — Gradient text animation on key phrases, updated type scale.
- **How It Works** — Step numbers styled with accent color.
- **IDE Strip** — Subtle glow treatment.
- **Final CTA** — Green button, gradient heading text.

## Motion

- Replace Framer Motion fade/slide animations with CSS `@keyframes card-enter` for staggered card entrances.
- Keep Framer Motion for viewport-triggered animations (simpler API).
- All CTA buttons: `transition: all 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)`.
