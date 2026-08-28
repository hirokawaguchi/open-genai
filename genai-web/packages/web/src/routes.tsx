import type { RouteObject } from 'react-router';
import { Navigate } from 'react-router';
import { ChatPage } from '@/features/chat/ChatPage';
import { ChatHistoryPage } from '@/features/chat-history/ChatHistoryPage';
import { ExAppPage } from '@/features/exapp/ExAppPage';
import { ExAppsPage } from '@/features/exapps/ExAppsPage';
import { GenerateDiagramPage } from '@/features/generate-diagram/GenerateDiagramPage';
import { GenerateImagePage } from '@/features/generate-image/GenerateImagePage';
import { GenerateTextPage } from '@/features/generate-text/GenerateTextPage';
import { LandingPage } from '@/features/landing/LandingPage';
import { KnowledgePage } from '@/open-genai/knowledge/KnowledgePage';
import { TeamAppCopyPage } from '@/features/team-apps/copy/TeamAppCopyPage';
import { TeamAppCreatePage } from '@/features/team-apps/create/TeamAppCreatePage';
import { TeamAppEditPage } from '@/features/team-apps/edit/TeamAppEditPage';
import { TeamAppsPage } from '@/features/team-apps/TeamAppsPage';
import { TeamMemberCreatePage } from '@/features/team-members/create/TeamMemberCreatePage';
import { TeamMemberEditPage } from '@/features/team-members/edit/TeamMemberEditPage';
import { TeamMembersPage } from '@/features/team-members/TeamMembersPage';
import { TeamCreatePage } from '@/features/teams/create/TeamCreatePage';
import { TeamEditPage } from '@/features/teams/edit/TeamEditPage';
import { TeamsPage } from '@/features/teams/TeamsPage';
import { TranslatePage } from '@/features/translate/TranslatePage';
import { WHISPER_EXAPP_PATH } from '@/layout/navItems';
import { AuditLogsPage } from '@/open-genai/admin-audit/AuditLogsPage';
import { ModelPolicyPage } from '@/open-genai/admin-modelpolicy/ModelPolicyPage';
import { NgWordPage } from '@/open-genai/admin-ngword/NgWordPage';
import { UserMgmtPage } from '@/open-genai/admin-usermgmt/UserMgmtPage';
import { ChoseiEditPage } from '@/open-genai/chosei/ChoseiEditPage';
import { ChoseiEventPage } from '@/open-genai/chosei/ChoseiEventPage';
import { ChoseiPage } from '@/open-genai/chosei/ChoseiPage';
import { DoccheckPage } from '@/open-genai/doccheck/DoccheckPage';
import { DocmakerPage } from '@/open-genai/docmaker/DocmakerPage';
import { PatchformApplicationPage } from '@/open-genai/patchform/PatchformApplicationPage';
import { PatchformApplyPage } from '@/open-genai/patchform/PatchformApplyPage';
import { PatchformDetailPage } from '@/open-genai/patchform/PatchformDetailPage';
import { PatchformEditPage } from '@/open-genai/patchform/PatchformEditPage';
import { PatchformInboxPage } from '@/open-genai/patchform/PatchformInboxPage';
import { PatchformPage } from '@/open-genai/patchform/PatchformPage';
import { PatchformProcedureEditPage } from '@/open-genai/patchform/PatchformProcedureEditPage';
import { PatchformProceduresPage } from '@/open-genai/patchform/PatchformProceduresPage';
import { PatchformWizardPage } from '@/open-genai/patchform/PatchformWizardPage';
import { PromptTemplatesPage } from '@/open-genai/prompt-templates/PromptTemplatesPage';
import { NotFound } from '@/NotFound';
import { ApiRequestDataFormatPage } from '@/pages/ApiRequestDataFormat';
import { isUseCaseEnabled } from '@/utils/isUseCaseEnabled';
import { Layout } from './layout/Layout';
import { AuthErrorPage } from './pages/AuthErrorPage';
import { SignedOutPage } from './pages/SignedOutPage';

export const createRoutes = (): RouteObject[] => {
  const optionalUseCaseRoutes: Array<RouteObject[] | null> = [
    isUseCaseEnabled('generate')
      ? [
          { path: 'generate', element: <GenerateTextPage /> },
          { path: 'generate/:chatId', element: <GenerateTextPage /> },
        ]
      : null,
    isUseCaseEnabled('translate')
      ? [
          { path: 'translate', element: <TranslatePage /> },
          { path: 'translate/:chatId', element: <TranslatePage /> },
        ]
      : null,
    isUseCaseEnabled('image')
      ? [
          { path: 'image', element: <GenerateImagePage /> },
          { path: 'image/:chatId', element: <GenerateImagePage /> },
        ]
      : null,
    isUseCaseEnabled('diagram')
      ? [
          { path: 'diagram', element: <GenerateDiagramPage /> },
          { path: 'diagram/:chatId', element: <GenerateDiagramPage /> },
        ]
      : null,
  ];

  const children: RouteObject[] = [
    { index: true, element: <LandingPage /> },
    { path: 'apps', element: <ExAppsPage /> },
    // ナレッジ管理 専用ページ。旧 exApp（タグ/登録/管理）は /knowledge へ集約しリダイレクト。
    // ナレッジ検索（rag）は従来どおり汎用 exApp を維持する。
    { path: 'knowledge', element: <KnowledgePage /> },
    { path: 'apps/:teamId/rag-tags', element: <Navigate to='/knowledge' replace /> },
    { path: 'apps/:teamId/rag-register', element: <Navigate to='/knowledge' replace /> },
    { path: 'apps/:teamId/rag-maintain', element: <Navigate to='/knowledge' replace /> },
    // プロンプトテンプレートは専用ページへ。旧 exApp URL（/apps/:teamId/prompt）は
    // リダイレクトする（ピン留め・ブックマーク・履歴リンクの互換のため）。
    { path: 'prompts', element: <PromptTemplatesPage /> },
    { path: 'apps/:teamId/prompt', element: <Navigate to='/prompts' replace /> },
    // 日程調整は専用ページへ（Compose profiles: ["chosei"]）。
    { path: 'chosei', element: <ChoseiPage /> },
    { path: 'chosei/events/:eventId', element: <ChoseiEventPage /> },
    { path: 'chosei/events/:eventId/edit', element: <ChoseiEditPage /> },
    { path: 'apps/:teamId/chosei', element: <Navigate to='/chosei' replace /> },
    // 書類領域分割チェックは専用ページへ（Compose profiles: ["doccheck"]）。
    { path: 'doccheck', element: <DoccheckPage /> },
    { path: 'apps/:teamId/doccheck', element: <Navigate to='/doccheck' replace /> },
    // マイ手続き（docmaker）は独立アプリの専用ページへ（patchform-app を共有）。
    { path: 'docmaker', element: <DocmakerPage /> },
    { path: 'apps/:teamId/docmaker', element: <Navigate to='/docmaker' replace /> },
    // 旧 URL 互換：フォーム配下の「マイ手続き」は docmaker へ寄せる。
    { path: 'patchform/my', element: <Navigate to='/docmaker' replace /> },
    // フォームは専用ページへ（Compose profiles: ["patchform"]）。
    { path: 'patchform', element: <PatchformPage /> },
    { path: 'patchform/inbox', element: <PatchformInboxPage /> },
    { path: 'patchform/inbox/:procedureId', element: <PatchformInboxPage /> },
    { path: 'patchform/procedures', element: <PatchformProceduresPage /> },
    { path: 'patchform/procedures/:procedureId', element: <PatchformProcedureEditPage /> },
    { path: 'patchform/apply/:procedureId', element: <PatchformApplyPage /> },
    { path: 'patchform/apply/:procedureId/wizard', element: <PatchformWizardPage /> },
    { path: 'patchform/applications/:applicationId', element: <PatchformApplicationPage /> },
    { path: 'patchform/:formId', element: <PatchformDetailPage /> },
    { path: 'patchform/:formId/edit', element: <PatchformEditPage /> },
    { path: 'apps/:teamId/patchform', element: <Navigate to='/patchform' replace /> },
    // 監査ログは管理者限定の専用ページへ。旧 exApp URL（/apps/:teamId/audit）は
    // リダイレクトする（ピン留め・ブックマーク・履歴リンクの互換のため）。
    { path: 'admin/audit', element: <AuditLogsPage /> },
    { path: 'apps/:teamId/audit', element: <Navigate to='/admin/audit' replace /> },
    // 利用者一括管理も管理者限定の専用ページへ。旧 exApp URL（/apps/:teamId/usermgmt）は
    // リダイレクトする（ピン留め・ブックマーク・履歴リンクの互換のため）。
    { path: 'admin/users', element: <UserMgmtPage /> },
    { path: 'apps/:teamId/usermgmt', element: <Navigate to='/admin/users' replace /> },
    // モデル利用制御・入力制限も管理者限定の専用ページへ。旧 exApp URL はリダイレクトする。
    { path: 'admin/model-policy', element: <ModelPolicyPage /> },
    { path: 'apps/:teamId/modelpolicy', element: <Navigate to='/admin/model-policy' replace /> },
    { path: 'admin/ngword', element: <NgWordPage /> },
    { path: 'apps/:teamId/ngword', element: <Navigate to='/admin/ngword' replace /> },
    { path: 'apps/:teamId/:exAppId', element: <ExAppPage /> },
    { path: 'chat', element: <ChatPage /> },
    { path: 'chat/:chatId', element: <ChatPage /> },
    { path: 'history', element: <ChatHistoryPage /> },
    ...optionalUseCaseRoutes.flatMap((routes) => routes ?? []),
    // 源内 /transcribe は Amazon Transcribe 前提。Open GENAI は Whisper exApp へ誘導する。
    { path: 'transcribe', element: <Navigate to={WHISPER_EXAPP_PATH} replace /> },
    { path: 'teams', element: <TeamsPage /> },
    { path: 'teams/create', element: <TeamCreatePage /> },
    { path: 'teams/:teamId/edit', element: <TeamEditPage /> },
    { path: 'teams/:teamId/members', element: <TeamMembersPage /> },
    { path: 'teams/:teamId/members/create', element: <TeamMemberCreatePage /> },
    { path: 'teams/:teamId/members/:userId/edit', element: <TeamMemberEditPage /> },
    { path: 'teams/:teamId/apps', element: <TeamAppsPage /> },
    { path: 'teams/:teamId/apps/create', element: <TeamAppCreatePage /> },
    { path: 'teams/:teamId/apps/:appId/edit', element: <TeamAppEditPage /> },
    { path: 'teams/:teamId/apps/:appId/copy', element: <TeamAppCopyPage /> },
    { path: 'docs/api-request-data-format', element: <ApiRequestDataFormatPage /> },
    { path: '*', element: <NotFound /> },
  ];

  return [
    { path: '/signed-out', element: <SignedOutPage /> },
    { path: '/auth-error', element: <AuthErrorPage /> },
    { path: '/', element: <Layout />, children },
  ];
};
