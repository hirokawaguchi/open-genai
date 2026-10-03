export type JigyoCheck = {
  id: string;
  label: string;
  done: boolean;
  doneBy?: string | null;
};

export type JigyoComment = {
  id: string;
  author: string;
  body: string;
  createdAt: string;
};

export type JigyoIssue = {
  id: string;
  projectId: string;
  projectKey: string;
  projectMode: string;
  teamId: string;
  number: number;
  title: string;
  body: string;
  status: string;
  priority: string | null;
  size: number | null;
  kind: string;
  leaveName: string;
  holidayDate?: string | null;
  completionText: string;
  completionMode: string | null;
  timeboxStart: string | null;
  templateId: string | null;
  templateName?: string;
  dueDate: string | null;
  createdAt: string;
  checks: JigyoCheck[];
  comments: JigyoComment[];
};

export type JigyoTemplate = {
  id: string;
  teamId: string;
  projectId: string;
  name: string;
  size: number;
  priority: string;
  completionText: string;
  completionMode: string;
  checks: string[];
  hasReceiptKey: boolean;
  keyHint: string | null;
};

export type JigyoProject = {
  id: string;
  teamId: string;
  key: string;
  name: string;
  description: string;
  mode: 'plan' | 'routine';
  status: string;
};

export type JigyoBox = {
  start: string;
  end: string;
  size: number;
  forecastSize?: number;
  routineReserve?: number;
  issues?: JigyoIssue[];
};

export type JigyoHome = {
  enabled?: boolean;
  error?: string;
  userId?: string;
  teamId: string | null;
  isAdmin?: boolean;
  isMember?: boolean;
  isChief?: boolean;
  chiefUserId?: string | null;
  headcount?: number | null;
  teams?: { teamId: string; teamName: string; admin: boolean; member: boolean }[];
  projects?: JigyoProject[];
  templates?: JigyoTemplate[];
  boxes?: { previous: JigyoBox; current: JigyoBox; next: JigyoBox };
  pace?: number;
  planIssues?: JigyoIssue[];
  leaveIssues?: JigyoIssue[];
  routine?: {
    templateId: string;
    name: string;
    count: number;
    openCount: number;
    size: number;
    issues: JigyoIssue[];
  }[];
};
