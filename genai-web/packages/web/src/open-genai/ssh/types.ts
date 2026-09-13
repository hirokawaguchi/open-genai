export type SshHost = {
  id: string;
  name: string;
  host: string;
  port: number;
  default_username: string;
  description: string;
  enabled: boolean;
  has_host_key: boolean;
  host_key?: string;
  created_at?: string;
  updated_at?: string;
};

export type SshConfig = {
  enabled?: boolean;
  is_admin?: boolean;
  idle_seconds?: number;
  max_sessions_per_user?: number;
  error?: string;
};

export type SshHostDraft = {
  name: string;
  host: string;
  port: number;
  default_username: string;
  description: string;
  host_key: string;
  enabled: boolean;
};

export const emptyHostDraft = (): SshHostDraft => ({
  name: '',
  host: '',
  port: 22,
  default_username: '',
  description: '',
  host_key: '',
  enabled: true,
});
