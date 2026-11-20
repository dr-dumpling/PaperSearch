/**
 * The settings window's environment: the platform basics (as for the backend's
 * MCP process), UTF-8 pipes, its screen and proxy, and its paths; never PaperSearch's keys.
 */
export declare function settingsWindowEnv(paths: {
    dataDir: string;
    configFile: string;
    cli: string;
    proEntry?: string;
}, env?: Record<string, string | undefined>): Record<string, string>;
export declare const SETTINGS_WINDOW_UNAVAILABLE: string;
export interface SettingsWindowOptions {
    /**
     * The installed backend (PAPER_SEARCH_SCHOOL_EXECUTABLE), read again after ``update``:
     * updating an install from before the rename (0.6.0) moves it.
     */
    executable: string | (() => string);
    /** A settings page (download, wait, keys, markdown) or an API key name; none for the settings home. */
    target?: string;
    env: Record<string, string | undefined>;
    exists?: (path: string) => boolean;
    run?: (file: string, args: string[], env: Record<string, string | undefined>) => Promise<{
        stdout: string;
        code: number;
    }>;
    /**
     * Brings the installed backend up to this PaperSearch before it draws the window
     * (autoUpdateSchool): the window is the backend's, and after an upgrade the old one
     * lacks the new pages. It decides for itself when not to (switched off, or a running
     * download holds the backend: the window then opens on the running one at once).
     */
    update?: () => Promise<unknown>;
}
/**
 * Open the settings (download folder, waits and reminders, API keys) in the
 * progress window: the open window switches to them, or one starts for them.
 * The window belongs to the school subscription download backend; without it
 * the answer says how to install it or use `paper-search setup` instead.
 */
export declare function openSettingsWindow(options: SettingsWindowOptions): Promise<Record<string, unknown>>;
//# sourceMappingURL=settingsWindow.d.ts.map