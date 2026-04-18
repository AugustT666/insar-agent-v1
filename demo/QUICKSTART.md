# Quick Start: Claude Design System Demo

## 30-Second Setup

### Option 1: Open Directly (Easiest)
```
Open this in your browser:
file:///home/august/insar-agent/demo/index.html
```

### Option 2: With Local Server (Recommended)
```bash
# Python 3.x
cd /home/august/insar-agent/demo
python -m http.server 8000

# Then open:
# http://localhost:8000
```

## What You'll See

A **conversation UI demo** showing:
- ✅ User message (right-aligned, blue background)
- ✅ Assistant response (left-aligned, neutral background)
- ✅ Skill reading step (reads "nisar-processing" workflow guide)
- ✅ Three tool call rows (env check, RSLC scan, DEM prep)
- ✅ Background job indicator (spinning ⟳, status, log path)
- ✅ Polling updates (fade-in animations)
- ✅ Completion message with output summary

## Toggle Dark Mode

Click the **🌙 moon icon** (top-right) to switch themes.
- Light mode: Warm #FAF9F5 background
- Dark mode: Warm #262624 background
- Your choice is saved automatically

## Key Design Elements

| Element | What It Shows |
|---------|---------------|
| **Message asymmetry** | User messages right, Assistant left (Claude signature) |
| **Skill reading** | Claude reading domain knowledge before responding |
| **Tool rows** | Tasks running in parallel (spinner = running, dot = waiting) |
| **Background job** | Long-running work with real-time status + log path |
| **Polling updates** | Incremental progress (fade-in animations) |
| **Colors** | Warm earth tones + semantic status colors (blue/green/orange/red) |
| **Spacing** | Generous 8px grid = breathing room |

## Files Explained

```
demo/
├── index.html          Main UI (136 lines HTML)
├── styles/main.css     Complete design system (673 lines CSS)
├── scripts/theme.js    Light/dark toggle (113 lines JS)
├── README.md           Full documentation
├── IMPLEMENTATION_SUMMARY.md    Technical specs
└── QUICKSTART.md       This file
```

## Design Highlights

🎨 **From Anthropic's MCP Apps Design Guidelines**
- Color tokens (light/dark modes)
- 8px spacing grid
- Typography system (24px heading, 16px body, 12px caption)
- No external dependencies (pure CSS)
- Accessibility-first (WCAG AA)

## Try These

1. **Resize the window** → Watch layout adapt (mobile-first)
2. **Toggle theme** → Click 🌙 → Refresh → Still dark (localStorage)
3. **Inspect with DevTools** → Check CSS custom properties in `<body>`
4. **Copy log path** → Click 📋 icon (placeholder, works in full app)

## Mobile Testing

Open on your phone or use DevTools device emulation:
- Messages adjust to 90% width
- Full-width on <600px screens
- Touch targets are 44x44pt (accessible)

## What Makes It "Claude"

✨ Warm color palette (#FAF9F5, #30302E) — not pure white/black
✨ Asymmetric message bubbles — user ≠ assistant visually
✨ Generous spacing — breathing room via 8px grid
✨ Inline tool status — no separate popovers
✨ Restrained animation — subtle fades and spins
✨ Semantic color only — blue=info, green=success
✨ No shadows — depth via borders and background only

## Extending It

Want to add your own messages?

1. Duplicate a `<div class="message">...</div>` block
2. For tool calls, add:
   ```html
   <div class="tool-call-row">
       <div class="tool-status-indicator running"><span class="spinner"></span></div>
       <div class="tool-call-content">
           <span class="tool-label">Your task</span>
           <span class="tool-status">Status text</span>
       </div>
   </div>
   ```
3. For background jobs, add:
   ```html
   <div class="background-job-indicator">
       <div class="job-header"><span class="job-spinner">⟳</span><span class="job-label">Task running</span></div>
       <div class="job-details">
           <div class="job-status-line"><span class="job-status-label">Status:</span><span class="job-status-value">In progress</span></div>
           <div class="job-log-line"><span class="job-log-label">Log:</span><code class="job-log-path">/path/to/log</code><button class="copy-button">📋</button></div>
       </div>
   </div>
   ```

## Browser Support

✅ Chrome/Edge 90+
✅ Firefox 88+
✅ Safari 14+
✅ Mobile (iOS Safari 14+, Chrome Android)

## No Dependencies

- ✅ Pure HTML (no frameworks)
- ✅ Pure CSS (no Tailwind, no Bootstrap)
- ✅ Vanilla JavaScript (no libraries)
- ✅ No build step (open in browser)
- ✅ No external fonts (system font stack)
- ✅ No icon library (emoji + Unicode)

## Questions?

- **How do I use this in my app?** → Read `README.md` for full guide
- **How do I customize colors?** → Edit `--color-*` variables in `styles/main.css`
- **How do I add animations?** → Define `@keyframes` in CSS
- **What are the design rules?** → See `IMPLEMENTATION_SUMMARY.md`

---

**That's it!** Enjoy the demo. Open `index.html` now.
