export type LedgerField = {
  id: string;
  label: string;
  type: 'text' | 'number' | 'date' | 'select' | 'longtext' | 'file';
  masked?: boolean;
  options?: string[];
  seen?: number;
};

export type LedgerGrant = { team_id: string; role: 'admin' | 'editor' | 'viewer' };

export type LedgerSystemField = {
  key: 'business_key' | 'status' | 'assignee' | 'registered_at' | 'comment' | string;
  label: string;
  visible: boolean;
};

export type LedgerDef = {
  id: string;
  name: string;
  tenant_id: string;
  statuses: string[];
  fields: LedgerField[];
  system?: LedgerSystemField[];
  grants: LedgerGrant[];
  role: 'admin' | 'editor' | 'viewer' | null;
  source_key?: string;
  created_at?: string;
  row_count?: number;
};

export type LedgerExtra = { label: string; value: string };

export type FieldOrigin = {
  origin: 'entered' | 'imported' | 'inferred';
  file_id?: string;
};

export type LedgerFile = {
  file_id: string;
  name: string;
  mime?: string;
  field_id?: string;
  role?: 'body' | 'former' | '';
  saved_at?: string;
  replaced_at?: string;
};

export type LedgerRow = {
  id: string;
  ledger_id: string;
  business_key: string;
  assignee: string;
  status: string;
  comment: string;
  fields: Record<string, string>;
  origins?: Record<string, FieldOrigin>;
  extras: LedgerExtra[];
  files: LedgerFile[];
  deleted_at: string;
  created_at: string;
  updated_at: string;
  revisions?: {
    id: string;
    actor_user_id: string;
    created_at: string;
    changes: { label?: string; before?: string; after?: string }[];
  }[];
};

export type LedgerConfig = {
  enabled?: boolean;
  has_tenant?: boolean;
  is_admin?: boolean;
  teams?: { id: string; name: string }[];
  team_ids?: string[];
  error?: string;
};
