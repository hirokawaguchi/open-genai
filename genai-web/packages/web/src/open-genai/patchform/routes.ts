import { DOCMAKER_LABEL } from '../docmaker/labels';
import { type PatchformMode, usePatchformApi } from './PatchformApiContext';

// マイ手続き（docmaker）の画面は庁内・庁外の両方で同じコンポーネントを描画する。
// リンク先とパンくずだけがモードで異なるため、ここに集約する。
// 庁内: react-router の内部ルート（/patchform, /docmaker）。
// 庁外: ゲスト SPA のルート（/public/mine, /public/new）。

export type Crumb = { label: string; to?: string };

export type PatchformRoutes = {
  mode: PatchformMode;
  /** マイ手続き一覧（匿名では空文字＝一覧なし）。 */
  myList: string;
  /** 申請（案件）ワークベンチ。本人編集モード（from=my）で開く。 */
  application: (id: string) => string;
  /** 作成ウィザード。opts.app があれば既存プロジェクトの条件変更モード。 */
  wizard: (procedureId: string, opts?: { app?: string }) => string;
  /** 手続きの公開管理（庁内のみ。庁外は null）。 */
  procedures: string | null;
  /** パンくずの先頭（庁内: ホーム/AIアプリ、庁外: なし）。 */
  homeCrumbs: Crumb[];
  /** マイ手続きのパンくずラベル。 */
  myListLabel: string;
};

const internalRoutes: PatchformRoutes = {
  mode: 'internal',
  myList: '/docmaker',
  application: (id) => `/patchform/applications/${encodeURIComponent(id)}?from=my`,
  wizard: (procedureId, opts) => {
    const base = `/patchform/apply/${encodeURIComponent(procedureId)}/wizard`;
    const params = new URLSearchParams();
    if (opts?.app) params.set('app', opts.app);
    params.set('from', 'my');
    return `${base}?${params.toString()}`;
  },
  procedures: '/patchform/procedures',
  homeCrumbs: [
    { label: 'ホーム', to: '/' },
    { label: 'AIアプリ', to: '/apps' },
  ],
  myListLabel: DOCMAKER_LABEL,
};

const guestRoutes: PatchformRoutes = {
  mode: 'guest',
  myList: '/public/mine',
  application: (id) => `/public/mine/${encodeURIComponent(id)}?from=my`,
  wizard: (procedureId, opts) => {
    const base = `/public/new/${encodeURIComponent(procedureId)}/wizard`;
    const params = new URLSearchParams();
    if (opts?.app) params.set('app', opts.app);
    params.set('from', 'my');
    return `${base}?${params.toString()}`;
  },
  procedures: null,
  homeCrumbs: [],
  myListLabel: 'マイ手続き',
};

// 匿名の共有リンク束（/public/p/{token}）。一覧・ウィザード・公開管理は持たない。
const anonymousRoutes: PatchformRoutes = {
  mode: 'anonymous',
  myList: '',
  application: (token) => `/public/p/${encodeURIComponent(token)}`,
  wizard: () => '',
  procedures: null,
  homeCrumbs: [],
  myListLabel: '申請',
};

export const usePatchformRoutes = (): PatchformRoutes => {
  const api = usePatchformApi();
  if (api.mode === 'anonymous') return anonymousRoutes;
  return api.mode === 'guest' ? guestRoutes : internalRoutes;
};
