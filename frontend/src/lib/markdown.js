import DOMPurify from "dompurify";
import { Marked } from "marked";

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

const marked = new Marked({
  gfm: true,
  breaks: true,
  renderer: {
    code({ text }) {
      return `<pre><code>${escapeHtml(text)}</code></pre>`;
    },
    html({ text }) {
      // Raw HTML in model output is shown as text, never interpreted.
      return escapeHtml(text);
    },
  },
});

// Model output is untrusted. No images (they would load third-party URLs and
// leak the reader's IP), no forms, no inline styles or handlers.
const PURIFY_CONFIG = {
  ALLOWED_TAGS: [
    "p", "br", "strong", "em", "b", "i", "s", "del", "a", "ul", "ol", "li", "blockquote",
    "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr",
    "th", "td", "hr", "div", "sup", "sub",
  ],
  ALLOWED_ATTR: ["href", "class", "colspan", "rowspan"],
  ALLOWED_URI_REGEXP: /^(?:https?:|mailto:)/i,
};

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer nofollow");
  }
});

export function renderMarkdown(text) {
  if (!text) return "";
  let html;
  try {
    html = marked.parse(text, { async: false });
  } catch {
    html = `<p>${escapeHtml(text)}</p>`;
  }
  html = html.replace(/<table>/g, '<div class="table-wrap"><table>').replace(/<\/table>/g, "</table></div>");
  return DOMPurify.sanitize(html, PURIFY_CONFIG);
}

export function safeHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}
