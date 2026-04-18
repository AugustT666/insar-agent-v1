/**
 * Theme Toggle Script
 * Manages light/dark mode with localStorage persistence
 * Follows Claude design system (prefers-color-scheme + explicit toggle)
 */

(function initializeTheme() {
    const THEME_KEY = 'insar-demo-theme';
    const THEME_LIGHT = 'light-mode';
    const THEME_DARK = 'dark-mode';

    /**
     * Get current theme preference:
     * 1. Check localStorage for explicit user choice
     * 2. Fall back to system preference (prefers-color-scheme)
     * 3. Default to light mode
     */
    function getInitialTheme() {
        const stored = localStorage.getItem(THEME_KEY);
        if (stored) {
            return stored;
        }

        // Check system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return THEME_DARK;
        }

        return THEME_LIGHT;
    }

    /**
     * Apply theme to document
     */
    function applyTheme(theme) {
        const html = document.documentElement;
        const body = document.body;

        // Remove both classes first
        body.classList.remove(THEME_LIGHT, THEME_DARK);

        // Add the current theme
        body.classList.add(theme);

        // Update HTML attribute (optional, for CSS attribute selectors)
        html.setAttribute('data-theme', theme);

        // Persist to localStorage
        localStorage.setItem(THEME_KEY, theme);

        // Update icon
        updateThemeIcon(theme);
    }

    /**
     * Update theme icon based on current theme
     * Moon icon = dark mode available (currently in light mode)
     * Sun icon = light mode available (currently in dark mode)
     */
    function updateThemeIcon(theme) {
        const toggle = document.getElementById('theme-toggle');
        if (!toggle) return;

        const icon = toggle.querySelector('.theme-icon');
        if (theme === THEME_DARK) {
            icon.textContent = '☀️'; // In dark mode, show sun to switch to light
        } else {
            icon.textContent = '🌙'; // In light mode, show moon to switch to dark
        }
    }

    /**
     * Toggle between themes
     */
    function toggleTheme() {
        const current = document.body.classList.contains(THEME_DARK) ? THEME_DARK : THEME_LIGHT;
        const next = current === THEME_DARK ? THEME_LIGHT : THEME_DARK;
        applyTheme(next);
    }

    /**
     * Initialize on page load
     */
    function init() {
        const theme = getInitialTheme();
        applyTheme(theme);

        // Attach event listener to toggle button
        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            toggle.addEventListener('click', toggleTheme);
        }

        // Listen for system preference changes (if user toggles OS dark mode)
        if (window.matchMedia) {
            const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
            darkModeQuery.addEventListener('change', (e) => {
                // Only auto-switch if user hasn't made an explicit choice
                const stored = localStorage.getItem(THEME_KEY);
                if (!stored) {
                    applyTheme(e.matches ? THEME_DARK : THEME_LIGHT);
                }
            });
        }
    }

    // Run on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
