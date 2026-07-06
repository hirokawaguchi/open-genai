import type { RouteObject } from 'react-router';
import { ChatPage } from '@/features/chat/ChatPage';
import { ChatHistoryPage } from '@/features/chat-history/ChatHistoryPage';
import { ExAppPage } from '@/features/exapp/ExAppPage';
import { ExAppsPage } from '@/features/exapps/ExAppsPage';
import { GenerateDiagramPage } from '@/features/generate-diagram/GenerateDiagramPage';
import { GenerateImagePage } from '@/features/generate-image/GenerateImagePage';
import { GenerateTextPage } from '@/features/generate-text/GenerateTextPage';
import { LandingPage } from '@/features/landing/LandingPage';
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
import { TranscribePage } from '@/features/transcribe/TranscribePage';
import { TranslatePage } from '@/features/translate/TranslatePage';
import { NotFound } from '@/NotFound';
import { ApiRequestDataFormatPage } from '@/pages/ApiRequestDataFormat';
import { isUseCaseEnabled } from '@/utils/isUseCaseEnabled';
import { Layout } from './layout/Layout';
import { AuthErrorPage } from './pages/AuthErrorPage';
import { SignedOutPage } from './pages/SignedOutPage';

export const createRoutes = (): RouteObject[] => {
  return [
    {
      path: '/signed-out',
      element: <SignedOutPage />,
    },
    {
      path: '/auth-error',
      element: <AuthErrorPage />,
    },
    {
      path: '/',
      element: <Layout />,
      children: [
        { index: true, element: <LandingPage /> },
        {
          path: 'apps',
          element: <ExAppsPage />,
        },
        { path: 'apps/:teamId/:exAppId', element: <ExAppPage /> },
        {
          path: 'chat',
          element: <ChatPage />,
        },
        {
          path: 'chat/:chatId',
          element: <ChatPage />,
        },
        { path: 'history', element: <ChatHistoryPage /> },
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
        { path: 'transcribe', element: <TranscribePage /> },
        { path: 'teams', element: <TeamsPage /> },
        { path: 'teams/create', element: <TeamCreatePage /> },
        {
          path: 'teams/:teamId/edit',
          element: <TeamEditPage />,
        },
        {
          path: 'teams/:teamId/members',
          element: <TeamMembersPage />,
        },
        {
          path: 'teams/:teamId/members/create',
          element: <TeamMemberCreatePage />,
        },
        {
          path: 'teams/:teamId/members/:userId/edit',
          element: <TeamMemberEditPage />,
        },
        {
          path: 'teams/:teamId/apps',
          element: <TeamAppsPage />,
        },
        {
          path: 'teams/:teamId/apps/create',
          element: <TeamAppCreatePage />,
        },
        {
          path: 'teams/:teamId/apps/:appId/edit',
          element: <TeamAppEditPage />,
        },
        {
          path: 'teams/:teamId/apps/:appId/copy',
          element: <TeamAppCopyPage />,
        },
        { path: 'docs/api-request-data-format', element: <ApiRequestDataFormatPage /> },
        { path: '*', element: <NotFound /> },
      ].flatMap((r) => (Array.isArray(r) ? r : r ? [r] : [])),
    },
  ].flatMap((r) => (Array.isArray(r) ? r : r ? [r] : []));
};
