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
    };
    socket.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (e) { return; }
      if (message.event === "sendToPropertyInspector") {
        listeners.forEach((fn) => fn(message.payload || {}));
      } else if (message.event === "didReceiveSettings") {
        settings = (message.payload && message.payload.settings) || settings;
      }
    };
    listeners.forEach((fn) => fn(null));
  }

  window.connectElgatoStreamDeckSocket = start;
  window.connectOpenActionSocket = start;
  if (globalThis.connectOpenActionSocketData) {
    Promise.resolve(globalThis.connectOpenActionSocketData)
      .then((details) => start.apply(null, details));
  }

  window.OpenWave = {
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
