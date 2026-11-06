/* Only loaded in PaperSearch's owned Camoufox process, never in the user's browser.
 * Camoufox's Juggler restores/focuses a native window for every automated click.
 * Suppress that focus while retaining its tab selection and trusted input path.
 * Explicit Page.bringToFront and native user input retain normal activation.
 */
var { ExtensionCommon } = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
var papersearchBackground = class extends ExtensionCommon.ExtensionAPI {
  onStartup() {
    if (!Services.prefs.getBoolPref("papersearch.background.enabled", false)) return;
    this.start().catch(async error => {
      console.error("PaperSearch background helper:", error);
      await IOUtils.writeJSON(PathUtils.join(PathUtils.profileDir, "papersearch-background.json"),
        {ready: false, session: Services.prefs.getStringPref("papersearch.background.session", ""),
         error: String(error).slice(0, 300)});
    });
  }
  onShutdown() { this.restore?.(); }
  async start() {
      const {PageTarget, TargetRegistry} = ChromeUtils.importESModule("chrome://juggler/content/TargetRegistry.js");
      const {PageHandler} = ChromeUtils.importESModule("chrome://juggler/content/protocol/PageHandler.js");
      const activate = PageTarget.prototype.activateAndRun;
      const bringToFront = PageHandler.prototype["Page.bringToFront"];
      if (typeof activate !== "function" || typeof bringToFront !== "function") {
        throw new Error("Unsupported Camoufox activation API");
      }
      const newPage = TargetRegistry.prototype._newPageInternal;
      if (typeof newPage !== "function") throw new Error("Unsupported Camoufox page API");
      const {Helper} = ChromeUtils.importESModule("chrome://juggler/content/Helper.js");
      const helper = new Helper();
      TargetRegistry.prototype._newPageInternal = async function({browserContextId}) {
        const win = Services.wm.getMostRecentWindow("navigator:browser");
        if (!win?.gBrowser) return await newPage.call(this, {browserContextId});
        const browserContext = this.browserContextForId(browserContextId);
        const tab = win.gBrowser.addTab("about:blank", {
          triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
          userContextId: browserContext.userContextId,
          skipAnimation: true,
        });
        let target = this._browserToTarget.get(tab.linkedBrowser);
        while (!target) {
          await helper.awaitEvent(this, TargetRegistry.Events.TargetCreated);
          target = this._browserToTarget.get(tab.linkedBrowser);
        }
        await target.activateAndRun();
        if (browserContext.crossProcessCookie.settings.timezoneId && await target.hasFailedToOverrideTimezone()) {
          throw new Error("Failed to override timezone");
        }
        return target.id();
      };
      const pending = new WeakMap();
      PageTarget.prototype.activateAndRun = async function(...args) {
        const win = this._window;
        let state = pending.get(win);
        if (!state) {
          state = {focus: win.focus, depth: 0};
          pending.set(win, state);
          win.focus = () => {};
        }
        state.depth++;
        try { return await activate.apply(this, args); }
        finally {
          if (--state.depth === 0) {
            win.focus = state.focus;
            pending.delete(win);
          }
        }
      };
      PageHandler.prototype["Page.bringToFront"] = async function(...args) {
        const win = this._pageTarget._window;
        if (win.windowState === win.STATE_MINIMIZED) win.restore();
        (pending.get(win)?.focus || win.focus).call(win);
        return await bringToFront.apply(this, args);
      };
      if (Services.prefs.getBoolPref("papersearch.background.bootstrap", false) &&
          !Services.wm.getMostRecentWindow("navigator:browser")) {
        const {AppConstants} = ChromeUtils.importESModule("resource://gre/modules/AppConstants.sys.mjs");
        const uri = Cc["@mozilla.org/supports-string;1"].createInstance(Ci.nsISupportsString);
        uri.data = "about:blank";
        const win = Services.ww.openWindow(null, AppConstants.BROWSER_CHROME_URL, "_blank",
          "chrome,dialog=no,all", uri);
        const focus = win.focus;
        win.focus = () => {};
        const {ctypes} = ChromeUtils.importESModule("resource://gre/modules/ctypes.sys.mjs");
        const user = ctypes.open("user32.dll");
        const getStyle = user.declare("GetWindowLongPtrW", ctypes.winapi_abi, ctypes.intptr_t,
          ctypes.voidptr_t, ctypes.int);
        const setStyle = user.declare("SetWindowLongPtrW", ctypes.winapi_abi, ctypes.intptr_t,
          ctypes.voidptr_t, ctypes.int, ctypes.intptr_t);
        const setPosition = user.declare("SetWindowPos", ctypes.winapi_abi, ctypes.int,
          ctypes.voidptr_t, ctypes.voidptr_t, ctypes.int, ctypes.int, ctypes.int, ctypes.int, ctypes.uint32_t);
        const setAlpha = user.declare("SetLayeredWindowAttributes", ctypes.winapi_abi, ctypes.int,
          ctypes.voidptr_t, ctypes.uint32_t, ctypes.unsigned_char, ctypes.uint32_t);
        const getAlpha = user.declare("GetLayeredWindowAttributes", ctypes.winapi_abi, ctypes.int,
          ctypes.voidptr_t, ctypes.uint32_t.ptr, ctypes.unsigned_char.ptr, ctypes.uint32_t.ptr);
        const native = win.docShell.treeOwner.QueryInterface(Ci.nsIBaseWindow);
        const hwnd = ctypes.voidptr_t(ctypes.UInt64(native.nativeHandle));
        const style = Number(getStyle(hwnd, -20).toString());
        const color = ctypes.uint32_t(), alpha = ctypes.unsigned_char(), alphaFlags = ctypes.uint32_t();
        if ((style & 0x00080000) && !getAlpha(hwnd, color.address(), alpha.address(), alphaFlags.address())) {
          user.close();
          throw new Error("Cannot preserve browser window opacity");
        }
        // NOACTIVATE alone still lets Gecko's first ShowWindow cover another
        // app. Keep only the initial, not-yet-painted window transparent until
        // it can be placed behind existing windows, then restore normal styles.
        setStyle(hwnd, -20, style | 0x08080000); // WS_EX_NOACTIVATE | WS_EX_LAYERED
        if (!setAlpha(hwnd, 0, 0, 2)) {
          setStyle(hwnd, -20, style);
          user.close();
          throw new Error("Cannot prepare the browser's background display");
        }
        let observer, timer;
        try {
          await new Promise((resolve, reject) => {
            timer = win.setTimeout(() => reject(new Error("Browser window initialization timed out")), 10000);
            observer = subject => {
              if (subject !== win) return;
              resolve();
            };
            Services.obs.addObserver(observer, "browser-delayed-startup-finished");
          });
        } finally {
          if (observer) Services.obs.removeObserver(observer, "browser-delayed-startup-finished");
          win.clearTimeout(timer);
          const placed = setPosition(hwnd, ctypes.voidptr_t(1), 0, 0, 0, 0, 0x0013); // HWND_BOTTOM; NOSIZE|NOMOVE|NOACTIVATE
          const opacityRestored = !(style & 0x00080000) || setAlpha(hwnd, color.value, alpha.value, alphaFlags.value);
          setStyle(hwnd, -20, style);
          user.close();
          win.focus = focus;
          if (!placed) throw new Error("Cannot place the browser behind existing windows");
          if (!opacityRestored) throw new Error("Cannot restore the browser window opacity");
        }
      }
      await IOUtils.writeJSON(PathUtils.join(PathUtils.profileDir, "papersearch-background.json"),
        {ready: true, session: Services.prefs.getStringPref("papersearch.background.session", "")});
      this.restore = () => {
        TargetRegistry.prototype._newPageInternal = newPage;
        PageTarget.prototype.activateAndRun = activate;
        PageHandler.prototype["Page.bringToFront"] = bringToFront;
      };
  }
};
