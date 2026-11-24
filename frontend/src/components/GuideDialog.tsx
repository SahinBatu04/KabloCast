import { useEffect, useRef, useState } from "react";
import { BookOpen, Radio, ShieldCheck, SlidersHorizontal, Smartphone, Wifi, X } from "lucide-react";
import { type Locale, MESSAGES } from "../i18n";

export type PhoneGuideId = "iphone16" | "iphone13";

interface GuideDialogProps {
  open: boolean;
  locale: Locale;
  onClose: () => void;
}

export function GuideDialog({ open, locale, onClose }: GuideDialogProps) {
  const t = MESSAGES[locale].guide;
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [tab, setTab] = useState<PhoneGuideId>("iphone16");

  useEffect(() => {
    const dlg = dialogRef.current;
    if (!dlg) return;
    if (open && !dlg.open) {
      dlg.showModal();
    } else if (!open && dlg.open) {
      dlg.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialogRef}
      closedby="any"
      onClose={onClose}
      aria-labelledby="kc-guide-title"
      className="kc-dialog m-auto max-h-[90dvh] w-[min(95vw,760px)] overflow-x-clip overflow-y-auto rounded-3xl border border-[var(--kc-border-strong)] bg-[var(--kc-bg-panel)] p-0 text-[var(--kc-ink-primary)] shadow-2xl"
    >
      {/* Sticky Header */}
      <div className="sticky top-0 z-10 border-b border-[var(--kc-border-subtle)] bg-[var(--kc-bg-panel)]/95 px-4 py-3.5 backdrop-blur sm:px-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <BookOpen className="h-5 w-5 shrink-0 text-[var(--kc-accent-ink)]" />
            <div className="min-w-0">
              <h2 id="kc-guide-title" className="truncate text-sm font-bold sm:text-base">
                {t.title}
              </h2>
              <p className="truncate text-[11px] text-[var(--kc-ink-muted)]">{t.subtitle}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.close}
            className="shrink-0 rounded-xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-1.5 text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div role="tablist" className="mt-3 grid grid-cols-2 gap-2">
          {(
            [
              { id: "iphone16" as const, label: t.tabs.usbc },
              { id: "iphone13" as const, label: t.tabs.lightning },
            ] as const
          ).map((item) => {
            const selected = tab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setTab(item.id)}
                className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold transition-colors ${
                  selected
                    ? "border-[var(--kc-accent)] bg-[var(--kc-accent-soft)] text-[var(--kc-accent-ink)]"
                    : "border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] text-[var(--kc-ink-secondary)] hover:text-[var(--kc-ink-primary)]"
                }`}
              >
                <Smartphone className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Body */}
      <div className="space-y-3.5 p-4 text-xs leading-relaxed text-[var(--kc-ink-secondary)] sm:p-5 sm:text-sm">
        <section className="rounded-2xl border border-[var(--kc-signal-emerald)]/30 bg-[var(--kc-signal-emerald-soft)] p-4">
          <h3 className="flex items-center gap-2 text-sm font-bold text-[var(--kc-signal-emerald)]">
            <ShieldCheck className="h-4 w-4 shrink-0" />
            {t.zeroQuotaTitle}
          </h3>
          <p className="mt-1.5 text-xs text-[var(--kc-ink-primary)] sm:text-sm">
            {t.zeroQuotaBody}
          </p>
        </section>

        <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
          <h3 className="mb-2.5 flex items-center gap-2 text-sm font-bold text-[var(--kc-ink-primary)]">
            <Radio className="h-4 w-4 text-[var(--kc-accent-ink)]" />
            {t.stepsTitle}
          </h3>
          <ol className="list-inside list-decimal space-y-2 text-xs sm:text-sm">
            <li className="text-[var(--kc-ink-primary)]">
              {tab === "iphone16" ? t.step1Usbc : t.step1Lightning}
            </li>
            <li className="text-[var(--kc-ink-primary)]">{t.step2}</li>
            <li className="text-[var(--kc-ink-primary)]">{t.step3}</li>
          </ol>
        </section>

        <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
          <h3 className="flex items-center gap-2 text-sm font-bold text-[var(--kc-ink-primary)]">
            <Wifi className="h-4 w-4 text-[var(--kc-accent-ink)]" />
            {t.noWifiTitle}
          </h3>
          <p className="mt-1.5 text-xs sm:text-sm">{t.noWifiBody}</p>
        </section>

        <section className="rounded-2xl border border-[var(--kc-border-subtle)] bg-[var(--kc-bg-elevated)] p-4">
          <h3 className="flex items-center gap-2 text-sm font-bold text-[var(--kc-ink-primary)]">
            <SlidersHorizontal className="h-4 w-4 text-[var(--kc-accent-ink)]" />
            {t.syncTitle}
          </h3>
          <p className="mt-1.5 text-xs sm:text-sm">{t.syncBody}</p>
        </section>
      </div>
    </dialog>
  );
}
