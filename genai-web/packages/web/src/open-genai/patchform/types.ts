export type FormStatus = 'draft' | 'published' | 'closed' | 'archived';
export type FormKind = 'definition' | 'reception';
export type FormWorkStatus = 'editing' | 'ready';
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
  properties?: { options?: Array<string | { label?: string; value?: string }>; [key: string]: unknown };
  visibleWhen?: VisibleWhenRule | VisibleWhenRule[];
  imi_type?: string;
  imi_subfields?: Record<string, string>;
};

export type DocRole = 'yoshiki' | 'attachment';

export type FormDefinition = {
  $version: string;
  metadata: { title: string; description?: string; doc_role?: DocRole };
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
  source_form_id?: string | null;
  source_title?: string | null;
  locked?: boolean;
  kind?: FormKind;
  work_status?: FormWorkStatus | null;
  receptions?: FormSummary[];
  reception_count?: number;
  has_opening?: boolean;
  tags?: string[];
};

export type FormDetail = FormSummary & {
  definition: FormDefinition;
  fill_definition?: FormDefinition;
  template?: SlotTemplate | null;
};

export type FormConfig = {
  public_endpoint?: string;
  retention_days?: number;
  enabled?: boolean;
  error?: string;
  spec_version?: string;
  catalog?: CatalogItem[];
  llm?: { model?: string; base_url?: string };
  mail?: { configured?: boolean; smtp?: boolean; dump?: boolean };
};

export type AssistGenerateResult = {
  source: 'llm' | 'template';
  definition: FormDefinition;
  notes?: string;
  model?: string;
};

export type AssistProcedureCreatedForm = { id: string; title: string; role: string };

export type AssistProcedurePreview = {
  source: 'llm' | 'template';
  notes?: string;
  model?: string;
  draft: Record<string, unknown>;
  preview: {
    name: string;
    warnings: string[];
    navigation: {
      found: boolean;
      title: string;
      questions: { label: string; options: string[] }[];
    };
    forms: { key: string; title: string; field_count: number; title_only?: boolean }[];
    notice: {
      name: string;
      description: string;
      rule_count: number;
      missing: string[];
    };
    outline?: {
      chapter_count: number;
      read: { id?: string; title?: string; kind?: string; form_count?: number }[];
    };
  };
};

export type AssistProcedureApply = {
  forms?: boolean;
  navigation?: boolean;
  notice?: boolean;
};

export type AssistProcedureResult = {
  procedure: (Procedure & { created_forms?: AssistProcedureCreatedForm[] }) | null;
  created_forms: AssistProcedureCreatedForm[];
  applied: { forms: boolean; navigation: boolean; notice: boolean };
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

export type ProcedureStatus = 'draft' | 'published' | 'archived';

export type ProcedureRule = {
  component_id: string;
  option: string;
  form_ids: string[];
  notes?: string;
  prepare?: string[];
  refs?: string[];
};

export type ProcedureChoiceField = {
  id: string;
  type: string;
  label: string;
  options: string[];
  option_items?: { value: string; label: string }[];
};

/** 答えで様式を足さない手続き（申請用紙1枚。ナビゲーションは使わない）。 */
export const omitsNavigation = (procedure: { choice_fields?: ProcedureChoiceField[] | null }) =>
  !(procedure.choice_fields || []).length;

export type Procedure = {
  id: string;
  name: string;
  description?: string | null;
  guide_form_id: string;
  guide_title?: string | null;
  guide_status?: FormStatus | null;
  guide_guest_token?: string | null;
  guide_public_url?: string | null;
  guide_reception_id?: string | null;
  guide_visibility?: FormVisibility | null;
  mapping: { rules: ProcedureRule[] };
  status: ProcedureStatus;
  creator_user_id?: string | null;
  creator_name?: string | null;
  created_at: string;
  updated_at: string;
  choice_fields?: ProcedureChoiceField[];
  warnings?: string[];
  can_edit?: boolean;
  notify_emails?: string[];
};

export type ApplicationFormStatus = 'none' | 'draft' | 'submitted' | 'withdrawn';

export type ApplicationForm = {
  id: string;
  title: string;
  guest_token?: string | null;
  public_url?: string | null;
  visibility?: FormVisibility | null;
  status: ApplicationFormStatus;
  answers?: Record<string, unknown>;
  definition?: FormDefinition;
  receipt_code?: string | null;
  respondent_label?: string | null;
  submitted_at?: string | null;
};

export type SlotKind = 'data' | 'yoshiki' | 'attach';
export type SlotRequired = 'required' | 'recommended' | 'optional';
export type SlotCardinality = 'one' | 'many';
export type ItemFulfillment = '' | 'form' | 'file';

/** 自治体が配布する様式ひな型（Word/PDF/Excel）。申請者はダウンロードして記入・添付する。 */
export type SlotTemplate = {
  file_id: string;
  filename: string;
  mime?: string;
  size?: number;
};

/** 申請束のアイテム（枠のインスタンス）。オンライン記入でもファイル添付でも満たせる。 */
export type ApplicationItem = {
  id: string;
  slot_id: string;
  title: string;
  kind: SlotKind;
  required: SlotRequired;
  cardinality: SlotCardinality;
  form_id?: string | null;
  fulfillment: ItemFulfillment;
  file_id?: string | null;
  file_name?: string | null;
  copy_index: number;
  added_by: string;
  guest_token?: string | null;
  public_url?: string | null;
  visibility?: FormVisibility | null;
  can_fill_online: boolean;
  template?: SlotTemplate | null;
  status: ApplicationFormStatus;
  // 記入と添付が併存しているかどうか（採用ソース切替UIの表示判定）
  form_submitted?: boolean;
  file_attached?: boolean;
  answers?: Record<string, unknown>;
  definition?: FormDefinition;
  receipt_code?: string | null;
  respondent_label?: string | null;
  submitted_at?: string | null;
};

export type ProcedureCatalogSlot = {
  slot_id: string;
  title: string;
  kind: SlotKind;
  form_id?: string | null;
  template?: SlotTemplate | null;
};

export type ProcedureCatalog = {
  procedure_id: string;
  slots: ProcedureCatalogSlot[];
};

export type ApplicationStatus = {
  auto: string;
  override: string;
  effective: string;
};

/** 記入内容の1フィールド分の変更（変更前→後）。 */
export type ApplicationChange = {
  label: string;
  before: string;
  after: string;
};

/** 申請束の変更履歴（誰が・いつ・何をしたか）。 */
export type ApplicationEvent = {
  actor_role: string;
  actor_user_id: string;
  action: string;
  target: string;
  detail: string;
  changes?: ApplicationChange[];
  created_at: string;
};

export type Application = {
  id: string;
  token: string;
  procedure_id: string;
  procedure_name: string;
  procedure_description?: string | null;
  title?: string;
  assignee?: string;
  deadline?: string;
  next_action_date?: string;
  owner_kind?: string;
  owner_key?: string;
  status?: ApplicationStatus;
  guide_form_id: string;
  guide_submission_id: string;
  form_ids: string[];
  notice: { notes?: string[]; prepare?: string[]; refs?: string[] };
  forms: ApplicationForm[];
  items: ApplicationItem[];
  events?: ApplicationEvent[];
  public_url: string;
  created_at: string;
  updated_at?: string;
};

/** マイ手続き一覧の1件（プロジェクトの要約）。 */
export type MyApplication = {
  id: string;
  token: string;
  title: string;
  procedure_id: string;
  procedure_name: string;
  status: ApplicationStatus;
  assignee: string;
  deadline: string;
  next_action_date: string;
  created_at: string;
  updated_at: string;
  done: number;
  total: number;
  public_url: string;
};

/** 作成ウィザードの必要書類プレビュー（dry-run 解決）。 */
export type ProcedureResolvePreviewItem = {
  slot_id: string;
  title: string;
  kind: SlotKind;
  required: SlotRequired;
  cardinality: SlotCardinality;
  has_template: boolean;
  can_fill_online: boolean;
};

export type ProcedureResolvePreview = {
  notice: { notes?: string[]; prepare?: string[]; refs?: string[] };
  items: ProcedureResolvePreviewItem[];
  count: number;
};

export type InboxItem = {
  kind: 'bundle' | 'form';
  id: string;
  created_at: string;
  title: string;
  label: string;
  procedure_id?: string;
  submitted?: number;
  total?: number;
  public_url?: string | null;
  form_id?: string;
  respondent_label?: string | null;
  withdrawn?: boolean;
};

export type InboxOpening = {
  kind: 'procedure' | 'form';
  id: string;
  title: string;
  guide_title?: string | null;
  public_url?: string | null;
};

export type InboxProcedure = {
  id: string;
  name: string;
  title: string;
  status: ProcedureStatus;
  guide_title?: string | null;
  public_url?: string | null;
  bundle_count: number;
  can_edit?: boolean;
  updated_at: string;
};

export type ProcedureShare = {
  id: string;
  name: string;
  internal_url: string;
  external_url?: string | null;
  internal_qr_svg: string;
  external_qr_svg?: string | null;
};

export type Inbox = {
  items: InboxItem[];
  procedures?: InboxProcedure[];
  openings: InboxOpening[];
  bundle_count: number;
  form_count: number;
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
