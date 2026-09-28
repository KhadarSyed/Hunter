import { useEffect, useRef, useState } from "react";
import { agentSocket, type WsMessage } from "../services/ws";

/**
 * Thin React wrapper around the `agentSocket` singleton (`services/ws.ts`).
 * Connects (idempotent) on mount, subscribes `onMessage`, and tracks
 * connection status — without changing `agentSocket` itself.
 */
export function useAgentSocket(onMessage: (msg: WsMessage) => void): { connected: boolean } {
  const [connected, setConnected] = useState(false);

  // Keep the latest callback in a ref so the subscription effect below does
  // not need to resubscribe every time the caller passes a new inline
  // arrow function.
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    agentSocket.connect();

    const unsubscribeMessage = agentSocket.onMessage((msg) => onMessageRef.current(msg));
    const unsubscribeStatus = agentSocket.onStatus(setConnected);

    return () => {
      unsubscribeMessage();
      unsubscribeStatus();
    };
  }, []);

  return { connected };
}
