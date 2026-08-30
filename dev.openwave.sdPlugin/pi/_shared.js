// Connecting to OpenDeck, once, for every inspector in this plugin.
//
// Two conventions are in the wild and OpenDeck ships both: the Elgato SDK
// calls a global function with the connection details, while OpenDeck's own
// newer plugins await a global promise of the same tuple. Supporting both is
// four lines and removes a whole class of "the panel is blank" bug.
//
// The context to send on is inActionInfo.context -- the ACTION's context, not
// the inspector's own uuid. Sending the inspector's uuid instead is accepted
// by the socket and then routed nowhere: settings are never saved, the
// plugin is never asked for its lists, and the panel sits empty with no error
// anywhere to explain it.
(function () {
  let socket = null;
  let context = null;
  let action = null;
  let settings = {};
  let answered = false;
  const listeners = [];

  function start(port, _uuid, registerEvent, _info, actionInfo) {
    const info = typeof actionInfo === "string"
      ? JSON.parse(actionInfo) : actionInfo;
    context = info.context;
    action = info.action;
    settings = (info.payload && info.payload.settings) || {};
    socket = new WebSocket("ws://127.0.0.1:" + port);
    socket.onopen = () => {
      socket.send(JSON.stringify({ event: registerEvent, uuid: _uuid }));
      OpenWave.ask();
      // Asking once is not enough: the socket can be open before the plugin
      // has finished registering, and a reply that lands then is answered to
      // nobody. Retry until a payload arrives, then stop.
      let tries = 0;
      const retry = setInterval(() => {
        if (answered || ++tries > 6) { clearInterval(retry); return; }
        OpenWave.ask();
      }, 600);
    };
    socket.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (e) { return; }
      if (message.event === "sendToPropertyInspector") {
        answered = true;
        report("payload " + JSON.stringify(message.payload || {}).length + "b");
        try {
          listeners.forEach((fn) => fn(message.payload || {}));
        } catch (err) {
          report("render threw: " + err);
        }
      } else if (message.event === "didReceiveSettings") {
        settings = (message.payload && message.payload.settings) || settings;
      }
    };
    window.addEventListener("error", (e) => report(
      "error: " + e.message + " @" + e.filename + ":" + e.lineno));
    listeners.forEach((fn) => fn(null));
  }

  window.connectElgatoStreamDeckSocket = start;
  window.connectOpenActionSocket = start;
  if (globalThis.connectOpenActionSocketData) {
    Promise.resolve(globalThis.connectOpenActionSocketData)
      .then((details) => start.apply(null, details));
  }

  // A webview inside a Tauri window has no console anyone can read, so the
  // inspector reports what it did back to the plugin, which has a log file.
  // Diagnosing "the dropdown is empty" any other way means guessing.
  function report(text) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({
      event: "sendToPlugin", context, action,
      payload: { debug: text, action },
    }));
  }

  window.OpenWave = {
    report,
    settings: () => settings,
    onPayload(fn) { listeners.push(fn); },
    ask() {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({
        event: "sendToPlugin", context, action,
        payload: { request: "targets", action },
      }));
    },
    save(changes) {
      Object.assign(settings, changes);
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({
        event: "setSettings", context, payload: settings,
      }));
    },
  };
})();
