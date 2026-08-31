import { Outlet, useLocation } from 'react-router';
import { Footer } from '@/components/ui/Footer';
import { Header } from '@/components/ui/Header';
import { SideNav } from '@/components/ui/SideNav';
import { isSidebarNavLayout } from '@/constants/navLayout';
import { useScrollRestoration } from '@/layout/hooks/useScrollRestoration';

// ストリーミングで本文が伸びる画面では、文書末のフッターが
// 自動スクロール（scrollIntoView）と干渉して表示がカクつく。
// /apps は Dify 対話など exApp（/apps/:teamId/:exAppId）を含む。
const FOOTER_HIDDEN_PATHS = ['/chat', '/image', '/apps'];

export const Layout = () => {
  const { pathname } = useLocation();
  const hideFooter = FOOTER_HIDDEN_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
  const sidebar = isSidebarNavLayout();

  useScrollRestoration();

  return (
    <div id='layoutRoot' className='flex min-h-dvh w-screen flex-col'>
      <Header className='sticky top-0 z-10' isLandingPage={pathname === '/'} />
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
  );
};
