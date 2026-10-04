import { useEffect, useRef, useState } from "react";

/**
 * Hosts the drag-to-edit Cp curve editor (public/cp_editor.html, the same
 * file Streamlit uses as a custom component). We speak the tiny part of the
 * Streamlit component protocol it uses:
 *   editor -> host: componentReady, setFrameHeight, setComponentValue
 *   host -> editor: render { args: { baseline } }
 */
export default function CpEditor({ baseline, onChange }) {
  const frame = useRef(null);
  const ready = useRef(false);
  const [height, setHeight] = useState(470);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const baselineRef = useRef(baseline);
  baselineRef.current = baseline;

  const sendRender = () => {
    const w = frame.current?.contentWindow;
    if (!w || !ready.current) return;
    w.postMessage({ type: "streamlit:render", args: { baseline: baselineRef.current || null } }, "*");
  };

  useEffect(() => {
    const onMsg = (evt) => {
      if (!frame.current || evt.source !== frame.current.contentWindow) return;
      const d = evt.data;
      if (!d || !d.isStreamlitMessage) return;
      if (d.type === "streamlit:componentReady") { ready.current = true; sendRender(); }
      // (setFrameHeight is ignored: the frame is same-origin, so it's sized to its real content below)
      else if (d.type === "streamlit:setComponentValue") onChangeRef.current?.(d.value);
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  useEffect(() => { sendRender(); }, [baseline?.key]);

  const observer = useRef(null);
  useEffect(() => () => observer.current?.disconnect(), []);
  const onLoad = () => {
    const doc = frame.current?.contentDocument;
    if (!doc) return;
    const measure = () => {
      const h = Math.ceil(doc.getElementById("wrap")?.getBoundingClientRect().height || 0) + 12;
      if (h > 200) setHeight(h);
    };
    observer.current?.disconnect();
    observer.current = new ResizeObserver(measure);
    observer.current.observe(doc.body);
    measure();
  };

  return (
    <iframe ref={frame} title="Target Cp curve editor" src="/cp_editor.html" className="editor-frame"
      onLoad={onLoad} style={{ height }} />
  );
}
