export type FormStatus = 'draft' | 'published' | 'closed' | 'archived';
export type FormVisibility = 'internal' | 'public' | 'both';
export type IdentityMode = 'required' | 'optional' | 'anonymous';

export type CatalogItem = {
  type: string;
  label: string;
  enabled: boolean;
  category: string;
  has_options: boolean;
  description?: string;
};

export type VisibleWhenRule = { field: string; eq?: string; in?: string[] };

export type FormComponent = {
  id: string;
  type: string;
  label: string;
  required?: boolean;
  hide_label?: boolean;
  placeholder?: string;
  properties?: { options?: string[]; [key: string]: unknown };
  visibleWhen?: VisibleWhenRule | VisibleWhenRule[];
  imi_type?: string;
};

export type FormDefinition = {
  $version: string;
  metadata: { title: string; description?: string };
  components: FormComponent[];
};

export type FormRole = 'admin' | 'owner' | 'editor' | 'viewer' | 'respondent';

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
  published_version?: number | null;
  published_at?: string | null;
  submission_count?: number;
  withdrawn_count?: number;
  draft_differs?: boolean;
  allow_draft?: boolean;
  allow_multiple?: boolean;
  identity_mode?: IdentityMode;
  has_name_composite?: boolean;
  editor_user_ids?: string[];
  viewer_user_ids?: string[];
  role?: FormRole | null;
  can_edit?: boolean;
  can_delete?: boolean;
  can_view_submissions?: boolean;
  can_reveal?: boolean;
  has_mynumber?: boolean;
  my_submitted?: boolean;
  my_has_draft?: boolean;
  created_at: string;
  updated_at: string;
  public_url: string;
};

export type FormDetail = FormSummary & {
  definition: FormDefinition;
  fill_definition?: FormDefinition;
};

export type AuditEvent = {
  id: string;
  form_id: string;
  submission_id?: string | null;
  actor_user_id: string;
  action: string;
  created_at: string;
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

export type UploadedFile = {
  file_id: string;
  filename: string;
  mime?: string;
  size?: number;
};

export type Submission = {
  id: string;
  receipt_code: string;
  submitter_user_id?: string | null;
  submitter_name?: string | null;
  respondent_label?: string | null;
  answers: Record<string, unknown>;
  created_at: string;
  version_id?: string | null;
  form_version?: number | null;
  published_at?: string | null;
  withdrawn?: boolean;
  withdrawn_at?: string | null;
  withdrawn_by?: string | null;
  definition?: FormDefinition | null;
};
