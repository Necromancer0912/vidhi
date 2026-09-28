// Minimal server-sent events reader for a fetch() response body.
// `onEvent(type, data)` may return true to stop reading early.
export async function readEventStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let type = "";
  let data = [];

  const dispatch = () => {
    const stop = data.length ? onEvent(type || "message", data.join("\n")) : false;
    type = "";
    data = [];
    return stop;
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline).replace(/\r$/, "");
        buffer = buffer.slice(newline + 1);

        if (line === "") {
          if (dispatch()) return;
        } else if (line.startsWith("event:")) {
          type = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          data.push(line.slice(5).replace(/^ /, ""));
        }
      }
    }
    dispatch();
  } finally {
    reader.cancel().catch(() => {});
  }
}
