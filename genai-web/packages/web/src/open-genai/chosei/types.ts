export type ResponseStatus = 'ok' | 'ng' | 'maybe';

export type ChoseiDateInput = {
  start_time: string;
  end_time?: string | null;
  is_all_day?: boolean;
};

export type ChoseiDate = {
  id: number;
  date_time: string;
  end_time?: string | null;
  is_all_day: boolean;
  created_at: string;
};

export type ChoseiEventSummary = {
  id: string;
  guest_token: string;
  title: string;
  description?: string | null;
  creator_name?: string | null;
  creator_user_id?: string | null;
  has_event_password: boolean;
  created_at: string;
  public_url: string;
};

export type ChoseiResponse = {
  id?: number;
  participant_name: string;
  participant_user_id?: string | null;
  event_date_id: number;
  status: ResponseStatus;
  date_time?: string;
};

export type ChoseiStatistics = Record<
  string,
  {
    date_time: string;
    ok: number;
    ng: number;
    maybe: number;
    participants: string[];
  }
>;

export type ChoseiEventDetail = {
  event: ChoseiEventSummary;
  dates: ChoseiDate[];
  responses: ChoseiResponse[];
  statistics: ChoseiStatistics;
};

export type ChoseiConfig = {
  public_endpoint?: string;
  retention_days?: number;
  enabled?: boolean;
  error?: string;
  llm?: { model?: string; base_url?: string };
};

export type ParsedDatesResult = {
  dates: (ChoseiDateInput & { label?: string })[];
  notes?: string;
  model?: string;
};

export type RecommendResult = {
  source: 'llm' | 'heuristic';
  recommended_date_id: number | null;
  recommended_date_time?: string | null;
  reasoning: string;
  ranking?: Array<{
    date_id: number;
    date_time?: string;
    score?: number;
    note?: string;
    ok?: number;
    maybe?: number;
    ng?: number;
  }>;
  model?: string;
  llm_error?: string;
};

export type InviteDraftResult = {
  subject: string;
  body: string;
  tips?: string;
  public_url?: string;
  model?: string;
};
