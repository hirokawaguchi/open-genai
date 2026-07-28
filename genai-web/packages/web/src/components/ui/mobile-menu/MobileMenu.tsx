import { type ComponentProps, forwardRef } from 'react';
import { Divider } from '@/components/ui/dads/Divider';
import { CloseIcon, HamburgerMenuButton } from '@/components/ui/dads/HamburgerMenuButton';
import { AccountIcon } from '@/components/ui/icons/AccountIcon';
import { MobileMenuItemButton, MobileMenuItemLink } from './MobileMenuItem';
import { MobileMenuSection } from './MobileMenuSection';

type Props = ComponentProps<'dialog'> & {
  isShowTeamManagementMenu: boolean;
  onClickSignout: () => void;
  onClose: () => void;
  /** ログイン中の表示名（ユーザ名）。未取得時は「アカウント」 */
  userDisplayName?: string;
};

export const MobileMenu = forwardRef<HTMLDialogElement, Props>((props, ref) => {
  const { isShowTeamManagementMenu, onClickSignout, onClose, userDisplayName, ...rest } = props;
  const accountLabel = userDisplayName?.trim() || 'アカウント';

  return (
    <dialog
      className='m-[unset] w-full h-screen max-h-[unset] max-w-[unset] overflow-visible backdrop:bg-opacity-gray-100 open:grid open:grid-rows-[auto_minmax(0,1fr)] lg:hidden! forced-colors:backdrop:bg-[#000b]'
      ref={ref}
      id='mobile-menu'
      aria-labelledby='mobile-menu-heading'
      {...rest}
    >
      <h2 id='mobile-menu-heading' className='sr-only'>
        メニュー
      </h2>
      <div className='flex h-14 mr-4 justify-end items-center bg-white px-1'>
        <HamburgerMenuButton
          className='px-1 pt-1 pb-1.5 rounded-infinity'
          aria-controls='mobile-menu'
          onClick={onClose}
        >
          <CloseIcon className='flex-none' />
          閉じる
        </HamburgerMenuButton>
      </div>
      <div className='flex h-full flex-col justify-between bg-white text-std-16N-170 text-solid-gray-800 print:hidden'>
        <nav className='flex h-full flex-col overflow-x-clip overflow-y-auto pt-1 pb-4 [scrollbar-gutter:stable]'>
          <div className='flex flex-col gap-4'>
            <ul className='py-1 pr-2 pl-4'>
              <li>
                <MobileMenuItemLink label='チャット' to='/chat' disableParentAriaCurrent />
              </li>
              <li>
                <MobileMenuItemLink label='AIアプリ' to='/apps' disableParentAriaCurrent />
              </li>
            </ul>
            <Divider />
            <div>
              <MobileMenuSection
                label={accountLabel}
                icon={(isOpen) => <AccountIcon className='shrink-0' isFilled={isOpen} />}
              >
                <ul>
                  {userDisplayName?.trim() && (
                    <li className='px-4 py-2 text-dns-14N-130 text-solid-gray-600'>
                      ログイン中: <span className='font-bold text-solid-gray-800'>{userDisplayName}</span>
                    </li>
                  )}
                  {isShowTeamManagementMenu && (
                    <li>
                      <MobileMenuItemLink label='チーム管理' to='/teams' />
                    </li>
                  )}
                  <li>
                    <MobileMenuItemLink label='利用履歴' to='/history' />
                  </li>
                  <li>
                    <MobileMenuItemButton
                      label='サインアウト'
                      onClick={() => {
                        onClickSignout();
                      }}
                    />
                  </li>
                </ul>
              </MobileMenuSection>
            </div>
          </div>
        </nav>
      </div>
    </dialog>
  );
});
