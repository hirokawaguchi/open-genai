import { useSWRConfig } from 'swr';
import { AccountMenu } from '@/components/ui/AccountMenu';
import { HamburgerIcon, HamburgerMenuButton } from '@/components/ui/dads/HamburgerMenuButton';
import { GlobalMenuLink } from '@/components/ui/GlobalMenuLink';
import { Logo } from '@/components/ui/Logo';
import { MobileMenu } from '@/components/ui/mobile-menu/MobileMenu';
import { useAuth } from '@/hooks/useAuth';
import { useMobileMenuHandler } from '@/layout/hooks/useMobileMenuHandler';
import { signOut as localSignOut } from '@/local/localAuth';

type Props = {
  className?: string;
  isLandingPage?: boolean;
};

export const Header = (props: Props) => {
  const { className, isLandingPage } = props;
  const { mobileMenuRef } = useMobileMenuHandler();

  const { data } = useAuth();
  const groups =
    (data?.tokens?.accessToken.payload['cognito:groups'] as unknown as string[] | undefined) ?? [];
  const userDisplayName =
    (data?.tokens?.accessToken.payload['username'] as string | undefined) ||
    (data?.tokens?.idToken.payload['cognito:username'] as string | undefined) ||
    (data?.tokens?.idToken.payload['email'] as string | undefined) ||
    '';

  const { cache } = useSWRConfig();

  const onClickSignout = () => {
    // SWRのキャッシュを全て削除する
    for (const key of cache.keys()) {
      cache.delete(key);
    }
    // localStorage の JWT を破棄し、backend のログアウト（→ /signed-out）へ遷移
    localSignOut();
  };

  return (
    <header
      className={`w-full h-(--header-height) border-b border-b-solid-gray-420 bg-white ${className ?? ''}`}
    >
      <div className='flex justify-start items-center gap-2 mx-auto w-full h-full px-6 max-w-(--page-width) lg:gap-6 lg:px-8'>
        <Logo isLandingPage={isLandingPage} />
        <nav className='hidden md:block'>
          <ul className='flex items-center gap-1.5'>
            <li>
              <GlobalMenuLink to='/chat' state={{ shouldReset: true }}>
                チャット
              </GlobalMenuLink>
            </li>
            <li>
              <GlobalMenuLink to='/apps'>AIアプリ</GlobalMenuLink>
            </li>
          </ul>
        </nav>

        <div className='hidden ml-auto md:flex h-full'>
          <AccountMenu
            onClickSignout={onClickSignout}
            userDisplayName={userDisplayName}
            isShowTeamManagementMenu={
              groups.includes('SystemAdminGroup') || groups.includes('TeamAdminGroup')
            }
          />
        </div>
        {/* For Mobile view */}
        <HamburgerMenuButton
          className={`relative ml-auto md:hidden rounded-infinity`}
          aria-controls='mobile-menu'
          aria-haspopup='dialog'
          onClick={() => mobileMenuRef.current?.showModal()}
        >
          <HamburgerIcon className='mt-0.5 flex-none' />
          メニュー
        </HamburgerMenuButton>
        <MobileMenu
          ref={mobileMenuRef}
          onClose={() => mobileMenuRef.current?.close()}
          onClickSignout={onClickSignout}
          userDisplayName={userDisplayName}
          isShowTeamManagementMenu={
            groups.includes('SystemAdminGroup') || groups.includes('TeamAdminGroup')
          }
        />
      </div>
    </header>
  );
};
