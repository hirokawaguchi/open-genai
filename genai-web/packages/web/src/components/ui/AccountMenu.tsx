import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react';
import { Link } from 'react-router';
import { ArrowDownIcon } from '@/components/ui/icons/ArrowDownIcon';
import { AccountIcon } from './icons/AccountIcon';

type Props = {
  className?: string;
  isShowTeamManagementMenu: boolean;
  onClickSignout: () => void;
  /** ログイン中の表示名（ユーザ名）。未取得時は「アカウント」 */
  userDisplayName?: string;
};

export const AccountMenu = (props: Props) => {
  const { className, isShowTeamManagementMenu, onClickSignout, userDisplayName } = props;
  const label = userDisplayName?.trim() || 'アカウント';

  return (
    <div className={`group relative h-full ${className ?? ''}`}>
      <Menu>
        <MenuButton
          className={`flex h-full w-fit max-w-56 items-center gap-1 px-2 text-dns-16B-130 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] data-active:bg-solid-gray-50 focus-visible:data-focus:rounded-4 focus-visible:data-focus:bg-yellow-300 focus-visible:data-focus:ring-[calc(6/16*1rem)] focus-visible:data-focus:ring-yellow-300 focus-visible:data-focus:outline-4 focus-visible:data-focus:-outline-offset-4 focus-visible:data-focus:outline-black focus-visible:data-focus:outline-solid focus-visible:data-focus:ring-inset lg:px-4 focus-visible:[&:not(data-focus)]:outline-hidden`}
          title={label}
        >
          {({ active }) => (
            <>
              <AccountIcon isFilled={active} />
              <span className='truncate'>{label}</span>
              <ArrowDownIcon className={`mt-0.5 ${active ? 'rotate-180' : ''}`} />
            </>
          )}
        </MenuButton>
        <MenuItems
          modal={false}
          className={`absolute top-full right-4 z-30 w-auto min-w-fit rounded-8 border border-solid-gray-420 bg-white py-2 shadow-1 focus:outline-hidden`}
        >
          {userDisplayName?.trim() && (
            <div
              className='px-4 py-2 text-oln-16N-100 text-solid-gray-600 border-b border-solid-gray-420 mb-1'
              role='presentation'
            >
              <p className='text-dns-14N-130 text-solid-gray-600'>ログイン中</p>
              <p className='truncate font-bold text-solid-gray-800' title={userDisplayName}>
                {userDisplayName}
              </p>
            </div>
          )}
          {isShowTeamManagementMenu && (
            <MenuItem>
              {({ focus }) => (
                <Link
                  to='/teams'
                  className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-4 text-oln-16N-100 text-nowrap text-solid-gray-800 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                >
                  チーム管理
                </Link>
              )}
            </MenuItem>
          )}
          <MenuItem>
            {({ focus }) => (
              <Link
                to='/history'
                className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-4 text-oln-16N-100 text-nowrap text-solid-gray-800 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
              >
                利用履歴
              </Link>
            )}
          </MenuItem>
          <MenuItem>
            {({ focus }) => (
              <button
                onClick={() => {
                  onClickSignout();
                }}
                className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-4 text-oln-16N-100 text-nowrap text-solid-gray-800 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
              >
                サインアウト
              </button>
            )}
          </MenuItem>
        </MenuItems>
      </Menu>
    </div>
  );
};
