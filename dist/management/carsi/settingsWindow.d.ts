/**
 * The settings window's environment: the platform basics (as for the backend's
 * MCP process), its screen and proxy, and its paths; never PaperSearch's keys.
 */
export declare function settingsWindowEnv(paths: {
    dataDir: string;
    configFile: string;
    cli: string;
}, env?: Record<string, string | undefined>): Record<string, string>;
export declare const SETTINGS_WINDOW_UNAVAILABLE: string;
export interface SettingsWindowOptions {
    /** The installed backend (PAPER_SEARCH_CARSI_EXECUTABLE). */
    executable: string;
    /** A settings page (download, wait, keys) or an API key name; none for the settings home. */
    target?: string;
    env: Record<string, string | undefined>;
    exists?: (path: string) => boolean;
    run?: (file: string, args: string[], env: Record<string, string | undefined>) => Promise<{
        stdout: string;
        code: number;
    }>;
}
/**
 * Open the settings (download folder, waits and reminders, API keys) in the
 * progress window: the open window switches to them, or one starts for them.
 * The window belongs to the school subscription download backend; without it
 * the answer says how to install it or use `paper-search setup` instead.
 */
export declare function openSettingsWindow(options: SettingsWindowOptions): Promise<Record<string, unknown>>;
//# sourceMappingURL=settingsWindow.d.ts.map