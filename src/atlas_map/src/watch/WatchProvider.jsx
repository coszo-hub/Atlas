import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { loadLive, loadReport, watchCounts, watchStates } from "./watch.js";

// The Watcher's data for the whole map: the day's report (loaded once), Nereus's live layer (on load, and every five
// minutes while the Watcher view is on), each sensor's state now, and the counts. `on` is the view (the owl button);
// it is remembered in this browser.
const WatchContext = createContext({ on: false, setOn: () => {}, states: {}, report: null, live: null, counts: null });
const KEY = "atlas.watcher";
const LIVE_EVERY = 5 * 60_000;

export function WatchProvider({ children }) {
  const [on, setOnState] = useState(() => { try { return localStorage.getItem(KEY) === "on"; } catch { return false; } });
  const setOn = v => { setOnState(v); try { localStorage.setItem(KEY, v ? "on" : "off"); } catch { /* private window */ } };
  const [report, setReport] = useState(null), [live, setLive] = useState(null);
  useEffect(() => {
    const ac = new AbortController();
    loadReport(ac.signal).then(setReport, () => setReport(null));
    return () => ac.abort();
  }, []);
  useEffect(() => {
    const ac = new AbortController();
    const get = () => loadLive(ac.signal).then(setLive, () => {});
    get();
    const id = on ? setInterval(get, LIVE_EVERY) : null;
    return () => { ac.abort(); if (id) clearInterval(id); };
  }, [on]);
  const value = useMemo(() => {
    const states = report ? watchStates(report, live) : {};
    return { on, setOn, report, live, states, counts: report ? watchCounts(states) : null };
  }, [on, report, live]);   // eslint-disable-line react-hooks/exhaustive-deps
  return <WatchContext.Provider value={value}>{children}</WatchContext.Provider>;
}

export const useWatch = () => useContext(WatchContext);
