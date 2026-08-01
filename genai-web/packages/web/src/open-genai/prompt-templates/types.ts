// プロンプトテンプレート専用ページ（源内 UI 制約回避の OpenGENAI 拡張）の型。
// backend `/prompts/*` → prompt-app の構造化 REST に対応する。

export type PromptTarget = 'content' | 'system';

/** 共有範囲。個人／チーム共有／全体公開／標準（管理者のみ）。 */
export type PromptShare = 'personal' | 'team' | 'public' | 'standard';

export type PromptTemplate = {
  id: string;
  title: string;
  body: string;
  target: PromptTarget;
  /** 区分の表示ラベル（標準／共有／個人）。 */
  kind: string;
  isStandard: boolean;
  /** 本文に含まれる {{変数}} 名の一覧。 */
  variables: string[];
  /** 現在の利用者が削除可能か。 */
  canDelete: boolean;
};

export type PromptTeam = {
  id: string;
  name: string;
};

export type PromptTemplatesResponse = {
  templates: PromptTemplate[];
  /** 標準テンプレートを作成できるか（システム管理者のみ）。 */
  canCreateStandard: boolean;
  /** 共有先に選べる所属チーム。 */
  teams: PromptTeam[];
};

export type CreateTemplateInput = {
  title: string;
  body: string;
  target: PromptTarget;
  share: PromptShare;
  share_team?: string;
};
