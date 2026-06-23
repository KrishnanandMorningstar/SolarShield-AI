// Shared API/WebSocket payload types (mirror backend/services.py + live.py).

export interface RunStatus {
  running: boolean;
  source: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  log: string;
}

export interface Metrics {
  master_events: number;
  confirmed: number;
  sxr_only: number;
  hxr_only: number;
  alert_episodes: number;
  tpr: number | null;
  far: number | null;
  median_lead_min: number | null;
  val_auc: number | null;
  test_auc: number | null;
}

export interface MasterEvent {
  event_id: string;
  status: "confirmed" | "sxr_only" | "hxr_only" | string;
  confidence?: string;
  flare_class?: string;
  onset_time?: string;
  peak_time_sxr?: string;
  peak_time_hxr?: string;
  end_time?: string;
  peak_sxr_flux_w_m2?: number | string;
  peak_hxr_counts_s?: number | string;
  hxr_leads_sxr_minutes?: number | string;
}

export interface ForecastAlert {
  alert_id?: string;
  start_time?: string;
  end_time?: string;
  peak_time?: string;
  peak_probability?: number | string;
  threshold?: number | string;
  forecast_horizon_min?: number | string;
}

export interface PayloadFile {
  name: string;
  size_bytes: number;
  modified_at: string;
}

export interface FilesResponse {
  solexs_dir: string;
  hel1os_dir: string;
  solexs: PayloadFile[];
  hel1os: PayloadFile[];
}

// ---- Live WebSocket protocol ----
export interface LiveEvent {
  event_id: string;
  status: string;
  confidence?: string;
  flare_class?: string;
  onset_time: string | null;
  peak_time_sxr: string | null;
  peak_time_hxr: string | null;
  end_time: string | null;
  peak_sxr_flux_w_m2: number | null;
  peak_hxr_counts_s: number | null;
  hxr_leads_sxr_minutes: number | null;
  fire_idx: number | null;
}

export interface LiveInit {
  type: "init";
  source: string;
  threshold: number;
  horizon_min: number;
  class_thresholds: Record<string, number>;
  t_start: string | null;
  t_end: string | null;
  total_frames: number;
  events: LiveEvent[];
}

export interface LiveFramePoint {
  t: string | null;
  sxr: number | null;
  hxr: number | null;
  prob: number | null;
}

export interface LiveFrame {
  type: "frame";
  from: number;
  to: number;
  total: number;
  points: LiveFramePoint[];
  fired_events: LiveEvent[];
  speed: number;
  paused: boolean;
}

export type LiveMessage =
  | LiveInit
  | LiveFrame
  | { type: "reset" }
  | { type: "done" }
  | { type: "error"; detail: string };
