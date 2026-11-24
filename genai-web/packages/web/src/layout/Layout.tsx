import { Suspense } from 'react';
import { Outlet, useLocation } from 'react-router';
import { Footer } from '@/components/ui/Footer';
import { Header } from '@/components/ui/Header';
import { SideNav } from '@/components/ui/SideNav';
import { isSidebarNavLayout } from '@/constants/navLayout';
import { useScrollRestoration } from '@/layout/hooks/useScrollRestoration';
import { BrowserPipHost } from '@/open-genai/browser/BrowserPipHost';
import { NoTenantBanner } from '@/open-genai/tenants/NoTenantBanner';

// ストリーミングで本文が伸びる画面では、文書末のフッターが
// 自動スクロール（scrollIntoView）と干渉して表示がカクつく。
// /apps は Dify 対話など exApp（/apps/:teamId/:exAppId）を含む。
const FOOTER_HIDDEN_PATHS = [
  '/chat',
  '/image',
  '/apps',
  '/notebook',
  '/nishukan',
  '/lms',
  '/procuretech-editor',
  '/procuretech-navigator',
  '/sengoku',
  '/budget',
  '/worldmonitor',
  '/browser',
  '/office',
  '/diagram',
  '/ledger',
];

export const Layout = () => {
  const { pathname } = useLocation();
  const hideFooter = FOOTER_HIDDEN_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
  const browserWindow = pathname === '/browser/window';
  const sidebar = isSidebarNavLayout();

  useScrollRestoration();

  if (browserWindow) {
    return (
      <Suspense
        fallback={
          <div className='flex h-dvh items-center justify-center bg-solid-gray-900 text-std-16N-170 text-solid-gray-300'>
            読み込み中…
          </div>
        }
      >
        <BrowserPipHost />
        <main id='mainContents' className='h-dvh w-screen overflow-hidden bg-solid-gray-900'>
          <Outlet />
        </main>
      </Suspense>
    );
  }

  return (
    <Suspense
      fallback={
        <div className='flex min-h-dvh items-center justify-center text-std-18N-160 text-solid-gray-800'>
          読み込み中…
        </div>
      }
    >
      <BrowserPipHost />
      <div id='layoutRoot' className='flex min-h-dvh w-screen flex-col'>
        <Header className='sticky top-0 z-10' isLandingPage={pathname === '/'} />
        <NoTenantBanner />
        <div className={`flex flex-1 ${sidebar ? 'md:flex-row' : 'flex-col'}`}>
          {sidebar && <SideNav />}
          <div className='flex min-w-0 flex-1 flex-col'>
            <main id='mainContents' className='flex-1'>
              <Outlet />
            </main>
            {!hideFooter && <Footer />}
          </div>
        </div>
      </div>
    </Suspense>
  );
};
