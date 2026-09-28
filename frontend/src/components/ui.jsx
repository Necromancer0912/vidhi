import { forwardRef, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "../lib/router";
import Icon from "./Icon";

// `onLime` swaps the chip to ink for use on lime panels.
export function Logo({ className = "", size = "md", onLime = false }) {
  const box = size === "sm" ? "h-7 w-7 text-[15px] rounded-[8px]" : "h-9 w-9 text-lg rounded-[10px]";
  const chip = onLime ? "bg-[#11130f] text-lime" : "bg-lime text-on-lime";
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <span className={`grid place-items-center font-semibold ${chip} ${box}`} aria-hidden="true">
        §
      </span>
      <span className={`font-medium tracking-[-0.02em] ${onLime ? "text-on-lime" : "text-ink"} ${size === "sm" ? "text-[17px]" : "text-[21px]"}`}>Vidhi</span>
    </span>
  );
}

const PILL_STYLES = {
  dark: { pill: "bg-invert text-on-invert hover:opacity-90", chip: "bg-on-invert text-invert" },
  lime: { pill: "bg-lime text-on-lime hover:bg-lime-strong", chip: "bg-[#11130f] text-lime" },
  outline: { pill: "border border-ink/80 text-ink hover:bg-ink/[0.04]", chip: "bg-invert text-on-invert" },
  glass: { pill: "border border-white/70 text-white hover:bg-white/10", chip: "bg-white text-[#11130f]" },
};

const PILL_SIZES = {
  md: { pill: "min-h-12 gap-3 pl-6 text-[15px]", chip: "h-9 w-9", icon: 17 },
  sm: { pill: "min-h-10 gap-2.5 pl-5 text-sm", chip: "h-7 w-7", icon: 15 },
};

// The reference's signature control: a pill label with a round arrow chip.
// Heights are minimums so long translated labels can wrap instead of spilling.
export function ArrowButton({ to, href, variant = "dark", size = "md", children, className = "", icon = "arrowUpRight", ...rest }) {
  const style = PILL_STYLES[variant];
  const dims = PILL_SIZES[size];
  const classes = `group inline-flex items-center rounded-full py-1.5 pr-1.5 text-left font-medium leading-snug transition ${dims.pill} ${style.pill} ${className}`;
  const inner = (
    <>
      <span>{children}</span>
      <span className={`grid shrink-0 place-items-center rounded-full transition-transform group-hover:rotate-45 ${dims.chip} ${style.chip}`}>
        <Icon name={icon} size={dims.icon} strokeWidth={2} />
      </span>
    </>
  );
  if (to) return <Link to={to} className={classes} {...rest}>{inner}</Link>;
  if (href) return <a href={href} className={classes} {...rest}>{inner}</a>;
  return <button type="button" className={classes} {...rest}>{inner}</button>;
}

export const IconButton = forwardRef(function IconButton({ icon, label, className = "", size = 18, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={`grid h-10 w-10 place-items-center rounded-full text-ink-2 transition hover:bg-ink/[0.06] hover:text-ink disabled:opacity-40 ${className}`}
      {...rest}
    >
      <Icon name={icon} size={size} />
    </button>
  );
});

// Native <dialog>: focus trapping, Escape and inert background come free.
export function Dialog({ open, onClose, title, children, footer, wide = false }) {
  const { t } = useTranslation();
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      aria-labelledby="dialog-title"
      className={`m-auto w-[calc(100%-24px)] rounded-[24px] bg-sheet p-0 text-ink shadow-2xl backdrop:bg-black/40 backdrop:backdrop-blur-[2px] ${wide ? "max-w-2xl" : "max-w-lg"}`}
    >
      {open && (
        <div className="flex max-h-[min(85vh,760px)] flex-col">
          <div className="flex items-center justify-between gap-4 border-b border-line px-6 py-4">
            <h2 id="dialog-title" className="text-lg font-medium">{title}</h2>
            <IconButton icon="x" label={t("common.close")} onClick={onClose} className="-mr-2 h-9 w-9" />
          </div>
          <div className="thin-scrollbar overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="border-t border-line px-6 py-4">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}
