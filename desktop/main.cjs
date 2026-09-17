"use strict";

const { app, BrowserWindow, session, shell, systemPreferences } = require("electron");
const {
  PRODUCTION_APP_URL,
  createNavigationPolicy,
  isAudioOnlyMediaRequest,
  resolveRuntimeAppUrl,
} = require("./security.cjs");

const SESSION_PARTITION = "persist:flare";
const hasSingleInstanceLock = app.requestSingleInstanceLock();
let applicationUrl = PRODUCTION_APP_URL;
let mainWindow = null;

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });

  app.whenReady().then(startApplication).catch((error) => {
    console.error("Unable to start Flare", error);
    app.quit();
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow(applicationUrl);
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}

function startApplication() {
  applicationUrl = resolveRuntimeAppUrl(process.env.FLARE_APP_URL, {
    isPackaged: app.isPackaged,
  });
  const flareSession = session.fromPartition(SESSION_PARTITION);

  configureMediaPermissions(flareSession, applicationUrl);
  createMainWindow(applicationUrl);
}

function configureMediaPermissions(flareSession, appUrl) {
  const policy = createNavigationPolicy(appUrl);
  const requestIsAllowed = (permission, requestingUrl, details) => permission === "media"
    && policy.isTrustedAppOrigin(requestingUrl)
    && isAudioOnlyMediaRequest(details);

  flareSession.setPermissionCheckHandler((_webContents, permission, requestingOrigin, details) => (
    requestIsAllowed(permission, requestingOrigin, details)
  ));

  flareSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const requestingUrl = details?.securityOrigin
      || details?.requestingUrl
      || webContents?.getURL()
      || "";
    if (!requestIsAllowed(permission, requestingUrl, details)) {
      callback(false);
      return;
    }

    if (process.platform !== "darwin") {
      callback(true);
      return;
    }

    const status = systemPreferences.getMediaAccessStatus("microphone");
    if (status === "granted") {
      callback(true);
      return;
    }
    if (status === "denied" || status === "restricted") {
      callback(false);
      return;
    }

    systemPreferences.askForMediaAccess("microphone")
      .then((granted) => callback(granted))
      .catch(() => callback(false));
  });
}

function createMainWindow(appUrl = PRODUCTION_APP_URL) {
  const policy = createNavigationPolicy(appUrl);
  const window = new BrowserWindow({
    title: "Flare",
    width: 1280,
    height: 820,
    minWidth: 860,
    minHeight: 620,
    show: false,
    backgroundColor: "#f7f7fb",
    webPreferences: {
      partition: SESSION_PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      webviewTag: false,
      devTools: !app.isPackaged,
      spellcheck: true,
    },
  });

  mainWindow = window;

  window.once("ready-to-show", () => window.show());

  const handleTopLevelNavigation = (event, targetUrl) => {
    const destination = policy.classify(targetUrl);
    if (destination === "app" || destination === "auth") return;

    event.preventDefault();
    if (destination === "external") void shell.openExternal(targetUrl);
  };

  window.webContents.on("will-navigate", handleTopLevelNavigation);
  window.webContents.on("will-redirect", handleTopLevelNavigation);

  window.webContents.setWindowOpenHandler(({ url }) => {
    const destination = policy.classify(url);
    if (destination === "app" || destination === "auth") {
      void window.loadURL(url);
    } else if (destination === "external") {
      void shell.openExternal(url);
    }
    return { action: "deny" };
  });

  window.webContents.on("before-input-event", (event, input) => {
    if (!input.meta || input.type !== "keyDown") return;

    const history = window.webContents.navigationHistory;
    if (input.key === "[" && history.canGoBack()) {
      event.preventDefault();
      history.goBack();
    } else if (input.key === "]" && history.canGoForward()) {
      event.preventDefault();
      history.goForward();
    }
  });

  window.on("closed", () => {
    if (mainWindow === window) mainWindow = null;
  });

  void window.loadURL(appUrl);
  return window;
}
