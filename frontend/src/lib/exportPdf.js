import { escapeHtml, renderMarkdown } from "./markdown";

// A4 at 96 dpi.
const PAGE_W = 794;
const PAGE_H = 1123;
const PAD_X = 56;
const PAD_TOP = 48;
const FOOTER_H = 64;

const STYLES = `
  .vx-page { width:${PAGE_W}px; height:${PAGE_H}px; padding:${PAD_TOP}px ${PAD_X}px ${FOOTER_H}px; box-sizing:border-box;
    background:#fff; color:#1d2019; position:relative; font-family:Geist, var(--font-script), system-ui, sans-serif; line-height:1.6; }
  .vx-body > * + * { margin-top:14px; }
  .vx-head { display:flex; justify-content:space-between; align-items:flex-end; padding-bottom:14px; border-bottom:2px solid #11130f; }
  .vx-brand { display:flex; align-items:center; gap:10px; font-size:20px; font-weight:600; }
  .vx-mark { width:28px; height:28px; border-radius:8px; background:#e3fa5c; display:grid; place-items:center; font-size:15px; }
  .vx-meta { font-size:11px; color:#6f756a; text-align:right; }
  .vx-label { font-size:10px; letter-spacing:.08em; text-transform:uppercase; color:#6f756a; margin-bottom:6px; }
  .vx-question { background:#f5f5ef; border-radius:10px; padding:14px 16px; font-size:13px; }
  .vx-answer { font-size:12.5px; color:#2d3129; }
  .vx-answer h1,.vx-answer h2,.vx-answer h3,.vx-answer h4 { font-size:14px; color:#11130f; margin:14px 0 6px; }
  .vx-answer p { margin:0 0 8px; }
  .vx-answer ul,.vx-answer ol { margin:0 0 8px; padding-left:20px; }
  .vx-answer ul { list-style:disc; } .vx-answer ol { list-style:decimal; }
  .vx-answer table { width:100%; border-collapse:collapse; font-size:11px; }
  .vx-answer th,.vx-answer td { border:1px solid #e2e5dc; padding:6px 8px; text-align:left; }
  .vx-answer pre { background:#f5f5ef; padding:10px; border-radius:8px; white-space:pre-wrap; font-size:11px; }
  .vx-sources { font-size:11.5px; }
  .vx-source { padding:8px 0; border-bottom:1px solid #e2e5dc; }
  .vx-note { font-size:10.5px; color:#555b50; background:#f5f5ef; border-radius:10px; padding:12px 14px; }
  .vx-foot { position:absolute; left:${PAD_X}px; right:${PAD_X}px; bottom:28px; display:flex; justify-content:space-between;
    font-size:10px; color:#8a9084; border-top:1px solid #e2e5dc; padding-top:10px; }
`;

function block(html, className = "") {
  const el = document.createElement("div");
  if (className) el.className = className;
  el.innerHTML = html; // every interpolated value below is escaped or sanitised
  return el;
}

// labels: translated strings for every piece of chrome on the page.
// labels.date is preformatted; pageLabel(n, total) returns "Page n of total" in the reader's language.
export async function exportAnswerPdf({ question, answer, sources, confidence, labels, lang, pageLabel }) {
  const [{ jsPDF }, { default: html2canvas }] = await Promise.all([import("jspdf"), import("html2canvas")]);

  const host = document.createElement("div");
  host.lang = lang;
  host.style.cssText = "position:fixed;left:-10000px;top:0;";
  host.appendChild(Object.assign(document.createElement("style"), { textContent: STYLES }));
  document.body.appendChild(host);

  const pages = [];
  const newPage = () => {
    const page = document.createElement("div");
    page.className = "vx-page";
    const body = document.createElement("div");
    body.className = "vx-body";
    page.appendChild(body);
    page.appendChild(block(`<span>${escapeHtml(labels.title)}</span><span class="vx-num"></span>`, "vx-foot"));
    host.appendChild(page);
    pages.push({ page, body });
    return body;
  };
  const maxBody = PAGE_H - PAD_TOP - FOOTER_H;

  let body = newPage();
  const place = (el) => {
    body.appendChild(el);
    if (body.scrollHeight > maxBody && body.childElementCount > 1) {
      body.removeChild(el);
      body = newPage();
      body.appendChild(el);
    }
  };

  try {
    place(
      block(
        `<div class="vx-brand"><span class="vx-mark">§</span>Vidhi</div>
         <div class="vx-meta">${escapeHtml(labels.title)}<br/>${escapeHtml(labels.date)}</div>`,
        "vx-head"
      )
    );
    place(block(`<div class="vx-label">${escapeHtml(labels.question)}</div><div class="vx-question">${escapeHtml(question)}</div>`));
    place(block(`<div class="vx-label">${escapeHtml(labels.answer)}</div>`));

    // Flow the answer element by element so page breaks fall between blocks.
    const answerRoot = block(renderMarkdown(answer), "vx-answer");
    [...answerRoot.children].forEach((child) => {
      const wrap = document.createElement("div");
      wrap.className = "vx-answer";
      wrap.appendChild(child);
      place(wrap);
    });

    if (sources.length) {
      const items = sources
        .map(
          (s) => `<div class="vx-source"><strong>${escapeHtml(s.document_title || "")}</strong>${
            s.section ? ` · ${escapeHtml(s.section)}` : ""
          }</div>`
        )
        .join("");
      const match = confidence == null ? "" : ` · ${escapeHtml(labels.match)}`;
      place(block(`<div class="vx-label">${escapeHtml(labels.sources)}${match}</div>${items}`, "vx-sources"));
    }
    place(block(escapeHtml(labels.disclaimer), "vx-note"));

    pages.forEach(({ page }, i) => {
      page.querySelector(".vx-num").textContent = pageLabel(i + 1, pages.length);
    });

    const pdf = new jsPDF({ unit: "pt", format: "a4" });
    for (let i = 0; i < pages.length; i++) {
      const canvas = await html2canvas(pages[i].page, { scale: 2, backgroundColor: "#ffffff", logging: false });
      if (i > 0) pdf.addPage();
      pdf.addImage(canvas.toDataURL("image/jpeg", 0.9), "JPEG", 0, 0, 595.28, 841.89);
    }
    pdf.save(`vidhi-answer-${new Date().toLocaleDateString("en-CA")}.pdf`);
  } finally {
    host.remove();
  }
}
