/** Where activation codes are checked; decided with the server. Empty: no server yet. */
export declare const DEFAULT_ACTIVATION_URL = "";
export type ActivationState = "none" | "active" | "expired";
export interface ActivationStatus {
    /** Whether there is a server to activate with. */
    service: boolean;
    state: ActivationState;
    /** The code's last four characters, all that is shown of it. */
    tail: string;
    /** The day it ends ("2027-03-01"); "" for none. */
    until: string;
}
export type ActivationResult = {
    ok: true;
    state: "active";
    tail: string;
    until: string;
} | {
    ok: false;
    code: string;
    message: string;
};
export declare function activationUrl(env?: Record<string, string | undefined>): string;
/** A code as typed, without spaces and in capitals; its form is settled with the server. */
export declare function normalizeCode(code: string): string;
/** Whether this computer is activated, and until when (`pro status`, the settings window). */
export declare function activationStatus(env?: Record<string, string | undefined>, now?: Date): ActivationStatus;
/** Hands the code to the activation server and keeps its answer. */
export declare function activatePro(options: {
    code: string;
    env?: Record<string, string | undefined>;
    timeoutMs?: number;
}): Promise<ActivationResult>;
/** Whether an install may go ahead: always without a server; with one, once activated. */
export declare function installAllowed(env?: Record<string, string | undefined>): boolean;
//# sourceMappingURL=activate.d.ts.map