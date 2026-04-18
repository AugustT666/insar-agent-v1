# insar-agent D-InSAR Workflow Demo

A static HTML/CSS/JS demo showcasing the insar-agent conversation UI design based on Anthropic's Claude design system.

## Features

✨ **Claude Design System Implementation**
- Warm earth-tone color palette (#FAF9F5 light, #262624 dark)
- 8px spacing grid with generous breathing room
- Asymmetric message bubbles (user right-aligned, assistant left-aligned)
- Semantic color system (info, success, warning, error)
- No external dependencies—pure CSS custom properties

🎨 **Interactive Patterns**
- Light/dark theme toggle with localStorage persistence
- Animated spinner for running tool calls
- Pulsing job indicator for background tasks
- Polling update animations (fade-in effect)
- Skill-reading step indicators with monospace details
- Focus states for accessibility (WCAG AA compliant)

📱 **Responsive Design**
- Mobile-first approach
- Full-width on mobile (<600px)
- Accessible touch targets (44x44pt minimum)
- Horizontal scrolling for long code paths

## File Structure

```
demo/
├── index.html           # Main HTML with D-InSAR workflow messages
├── styles/
│   └── main.css        # Claude design system + components (673 lines)
├── scripts/
│   └── theme.js        # Light/dark theme toggle with localStorage
└── README.md           # This file
```

## Usage

### Quick Start
1. Open `demo/index.html` in a web browser (no build step required)
2. Click the moon/sun icon (top-right) to toggle dark mode
3. Theme preference is saved to localStorage

### Local Server (Recommended for Testing)
```bash
# Python 3
python -m http.server 8000 --directory /home/august/insar-agent/demo

# Node.js (if installed)
npx http-server demo/

# Then open: http://localhost:8000
```

## Design Patterns Implemented

### 1. Color Tokens
- **Light mode**: #FFFFFF background, #1A1A1A text, #FAF9F5 secondary
- **Dark mode**: #1A1A1A background, #ECECEC text, #262624 secondary
- Automatic light/dark switching via `prefers-color-scheme` media query
- User can override with toggle button (persisted in localStorage)

### 2. Message Components

**User Messages**
- Right-aligned, filled background (#0066CC)
- White text, 12px border-radius
- Max 70% width on desktop, 90% on mobile

**Assistant Messages**
- Left-aligned, transparent background
- Support for nested lists, code blocks, and inline formatting

**Skill Reading Steps**
- Subtle background (#F5F3F0 light, #30302E dark)
- 3px left border (info blue)
- Icon + semibold label + monospace detail line

### 3. Tool Call Rows
- Secondary background with 1px border
- Flex layout: status icon + label + status text
- **Running state**: 16px spinner (1s rotation)
- **Pending state**: static dot (◯)
- **Success state**: green checkmark
- Hover state shifts background color

### 4. Background Job Indicator
- Info background (#D6E4F6 light, #1E3A5F dark)
- 3px left border (info blue)
- Rotating spinner icon (⟳, 1s animation)
- Status line: "Processing interferogram (Step 3 of 6)"
- **Log path**: monospace code with copy button (📋)
- **Polling updates**: fade-in animations with timestamps

### 5. Accessibility
- All colors meet WCAG AA contrast (4.5:1 text, 3:1 UI)
- Focus states: 2px blue outline with 2px offset
- Button/link minimum size: 44x44pt on mobile
- Semantic HTML: `<h1>`, `<p>`, `<ol>`, `<code>`, `<button>`
- Proper ARIA labels on interactive elements

## D-InSAR Workflow Messages

The demo includes a realistic 5-message workflow:

1. **User Prompt**: "I want to process a pair of NISAR RSLC files..."
2. **Assistant Response**: Overview + skill-reading step
3. **Data Preparation**: Three tool-call rows (env check, RSLC scan, DEM prep)
4. **Background Job**: Running indicator with polling updates
5. **Completion**: Final output summary with key product paths

## CSS Architecture

### Layout Layers
```
App Container (flex column, full viewport)
├── Header (fixed height, secondary bg)
└── Chat Container (flex 1, scrollable, max-width 900px)
    ├── User Message (right-aligned)
    ├── Assistant Message (left-aligned)
    │   ├── Text content
    │   ├── Skill reading step
    │   ├── Tool call rows
    │   ├── Background job indicator
    │   │   ├── Job header + spinner
    │   │   ├── Job details (status line + log path)
    │   │   └── Polling updates
    │   └── Output summary
    └── ...
```

### Spacing System (8px Grid)
```
--spacing-xs: 4px      (half grid)
--spacing-sm: 8px      (1 grid)
--spacing-md: 16px     (2 grids)
--spacing-lg: 24px     (3 grids) ← message separator
--spacing-xl: 32px     (4 grids)
--spacing-2xl: 48px    (6 grids)
--spacing-3xl: 64px    (8 grids)
```

### Typography Scale
```
Heading: 24px, 600 weight, 1.25 line-height
Body:    16px, 400 weight, 1.4 line-height
Caption: 12px, 400 weight (used for labels, timestamps)
```

## No External Dependencies

✅ **Pure CSS** — No utility library (no Tailwind, no Bootstrap)
✅ **No icons library** — Uses emoji and monospace symbols
✅ **No fonts** — System font stack with monospace fallback
✅ **No animations library** — Keyframes defined in CSS
✅ **No JavaScript framework** — Vanilla JS for theme toggle

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari 14+, Chrome Android)

Requirements:
- CSS custom properties (`var()`)
- CSS media queries (`prefers-color-scheme`)
- ES6 JavaScript (arrow functions, `const`/`let`)

## Extending the Demo

### Add More Messages
1. Copy a message div: `<div class="message assistant-message">...</div>`
2. Add your content (text, lists, code, etc.)
3. For tool calls, use `.tool-call-row` with status indicator
4. For background jobs, use `.background-job-indicator`

### Customize Colors
Edit the CSS custom properties in `styles/main.css`:
```css
:root {
    --color-info-bg: #D6E4F6;      /* Change this */
    --color-info-border: #0066CC;  /* And this */
}
```

### Add New Status Icons
Tool call statuses (`.tool-status-indicator`) support three classes:
- `.running` — pulsing spinner
- `.pending` — static dot
- `.success` — checkmark

Add more in the HTML and style in CSS.

### Mobile Customizations
The demo includes a `@media (max-width: 600px)` breakpoint. Adjust in CSS if needed.

## Validation Checklist

- ✅ Color contrast (WCAG AA): 4.5:1 text, 3:1 UI components
- ✅ Focus states: 2px outline with 2px offset
- ✅ Touch targets: 44x44pt minimum on mobile
- ✅ Semantic HTML: proper heading hierarchy, button/link roles
- ✅ Light/dark modes: both tested visually
- ✅ Animations: <2s duration, smooth easing
- ✅ No external assets: all CSS, all local

## Sources

- **Anthropic MCP Apps Design Guidelines**: https://claude.com/docs/connectors/building/mcp-apps/design-guidelines
- **WCAG 2.1 Accessibility Guidelines**: https://www.w3.org/WAI/WCAG21/quickref/
- **MDN Web Docs**: https://developer.mozilla.org/en-US/

## License

This demo is part of the insar-agent project and follows its license.
