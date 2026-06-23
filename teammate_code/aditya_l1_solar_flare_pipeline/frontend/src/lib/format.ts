export function fmtTime(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
}

export function fmtClock(value?: string | number | null): string {
  if (value === null || value === undefined) return "--:--:--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toISOString().slice(11, 19);
}

export function fmtDate(value?: string | number | null): string {
  if (value === null || value === undefined) return "-------";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-------";
  return d.toISOString().slice(0, 10);
}

export function fmtSci(value?: number | string | null, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n !== 0 && Math.abs(n) < 0.001) return n.toExponential(digits);
  return n.toFixed(digits);
}

export function fmtNum(value?: number | string | null, digits = 1): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function fmtPct(value?: number | null, alreadyPct = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(alreadyPct ? value : value * 100).toFixed(1)}%`;
}

export function statusColor(status?: string): string {
  switch (status) {
    case "confirmed":
      return "#ff5d6c";
    case "sxr_only":
      return "#3fbdf0";
    case "hxr_only":
      return "#f6a04d";
    default:
      return "#8aa0c0";
  }
}

export function statusLabel(status?: string): string {
  switch (status) {
    case "confirmed":
      return "Confirmed";
    case "sxr_only":
      return "SXR only";
    case "hxr_only":
      return "HXR only";
    default:
      return status ?? "—";
  }
}

// GOES-style class colour for flare-class badges.
export function classColor(flareClass?: string): string {
  const letter = (flareClass ?? "").charAt(0).toUpperCase();
  switch (letter) {
    case "X":
      return "#ff5d6c";
    case "M":
      return "#ff944d";
    case "C":
      return "#ffc857";
    case "B":
      return "#3ddc97";
    default:
      return "#7fa6d0";
  }
}
