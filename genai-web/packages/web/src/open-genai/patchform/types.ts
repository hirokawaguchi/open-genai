export type FormStatus = 'draft' | 'published' | 'closed' | 'archived';
export type FormVisibility = 'internal' | 'public' | 'both';

export type CatalogItem = {
  type: string;
  label: string;
  enabled: boolean;
  category: string;
  has_options: boolean;
};

export type FormComponent = {
  id: string;
  type: string;
  label: string;
  required?: boolean;
  placeholder?: string;
  properties?: { options?: string[]; [key: string]: unknown };
  visibleWhen?: { field: string; eq?: string; in?: string[] } | Array<{ field: string; eq?: string; in?: string[] }>;
  imi_type?: string;
};

export type FormDefinition = {
  $version: string;
  metadata: { title: string; description?: string };
  components: FormComponent[];
};

export type FormSummary = {
  id: string;
  guest_token: string;
  title: string;
  description?: string | null;
  status: FormStatus;
  visibility: FormVisibility;
  has_pin: boolean;
  creator_user_id?: string | null;
  creator_name?: string | null;
  retention_days: number;
  published_version_id?: string | null;
  created_at: string;
  updated_at: string;
  public_url: string;
};

export type FormDetail = FormSummary & {
  definition: FormDefinition;
};

export type FormConfig = {
  public_endpoint?: string;
  retention_days?: number;
  enabled?: boolean;
  error?: string;
  spec_version?: string;
  catalog?: CatalogItem[];
  llm?: { model?: string; base_url?: string };
};

export type AssistGenerateResult = {
  source: 'llm' | 'template';
  definition: FormDefinition;
  notes?: string;
  model?: string;
};

export type AssistInviteResult = {
  subject: string;
  body: string;
  source?: string;
  notes?: string;
};

export type Submission = {
  id: string;
  receipt_code: string;
  submitter_user_id?: string | null;
  submitter_name?: string | null;
  answers: Record<string, unknown>;
  created_at: string;
};
