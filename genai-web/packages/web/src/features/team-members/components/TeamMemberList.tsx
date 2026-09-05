import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react';
import { PiPencilLine, PiTrash } from 'react-icons/pi';
import { Link, useParams } from 'react-router';
import { MoreVertIcon } from '@/components/ui/icons/MoreVertIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/Tooltip';
import { useFocusNewItemOnLoadMore } from '@/hooks/useFocusNewItemOnLoadMore';
import { useTeamMembers } from '../hooks/useTeamMembers';

type Props = {
  handleOpenDeleteModal: (userId: string) => void;
};

export const TeamMemberList = (props: Props) => {
  const { handleOpenDeleteModal } = props;

  const { teamId } = useParams();

  const { members, hasMore, isValidating, loadMore } = useTeamMembers();

  const { listRef, loadMoreWithFocus } = useFocusNewItemOnLoadMore<HTMLUListElement>({
    itemsLength: members.length,
    focusSelector: 'span[tabindex="-1"]',
  });

  if (!isValidating && (!members || members.length === 0)) {
    return <div className='mt-4 flex w-full justify-center'>メンバーが登録されていません</div>;
  }

  return (
    <>
      <h2
        tabIndex={-1}
        id='user-list-heading'
        className={`my-4 inline-flex text-std-18B-160 focus-visible:rounded-4 focus-visible:bg-yellow-300 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:outline-black focus-visible:outline-solid lg:text-std-20B-150`}
      >
        メンバー
      </h2>
      <ul ref={listRef} className='flex w-full flex-col'>
        {members.map((member) => (
          <li
            className='relative grid w-full grid-cols-[1fr_auto] items-center border-b border-solid-gray-420'
            key={member.userId}
          >
            <p className='flex flex-col items-start gap-2.5 px-4 py-3.5 text-dns-16N-130 leading-tight! sm:flex-row lg:items-center'>
              <span
                tabIndex={-1}
                className='break-all focus-visible:rounded-4 focus-visible:outline-solid focus-visible:outline-4 focus-visible:outline-black focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:bg-yellow-300 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300'
              >
                {member.username}
              </span>
              {member.isPrimary && (
                <span className='rounded-4 bg-blue-50 px-2 py-1 text-oln-16N-100'>
                  主所属
                </span>
              )}
              {member.isAdmin && (
                <span className='rounded-4 bg-solid-gray-50 px-2 py-1 text-oln-16N-100'>
                  チーム管理者
                </span>
              )}
            </p>
            <div className='relative flex flex-none px-2'>
              <Menu>
                <Tooltip placement='left'>
                  <TooltipTrigger asChild>
                    <MenuButton
                      className={`flex size-9 items-center justify-center rounded-4 after:absolute after:-inset-full after:m-auto after:h-11 after:w-11 hover:bg-solid-gray-50 hover:-outline-offset-[calc(2/16*1rem)] hover:outline-black hover:outline-solid focus-visible:bg-yellow-300 focus-visible:ring-[calc(6/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:-outline-offset-4 focus-visible:outline-black focus-visible:outline-solid focus-visible:ring-inset`}
                    >
                      <MoreVertIcon aria-label='メンバーの操作' role='img' className='mt-0.5' />
                    </MenuButton>
                  </TooltipTrigger>
                  <TooltipContent aria-hidden={true}>メンバーの操作</TooltipContent>
                </Tooltip>

                <MenuItems
                  modal={false}
                  className={`absolute top-full right-0 z-10 w-auto min-w-fit rounded-8 border border-solid-gray-420 bg-white py-2 shadow-1 focus:outline-hidden`}
                >
                  <MenuItem>
                    {({ focus }) => (
                      <Link
                        to={`/teams/${teamId}/members/${member.userId}/edit`}
                        className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap text-solid-gray-800 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                      >
                        <PiPencilLine aria-hidden={true} className='text-lg' />
                        編集
                      </Link>
                    )}
                  </MenuItem>
                  <MenuItem>
                    {({ focus }) => (
                      <button
                        type='button'
                        onClick={() => handleOpenDeleteModal(member.userId)}
                        aria-haspopup='dialog'
                        className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap text-error-1 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:text-solid-gray-800 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                      >
                        <PiTrash aria-hidden={true} className='text-lg' />
                        削除
                      </button>
                    )}
                  </MenuItem>
                </MenuItems>
              </Menu>
            </div>
          </li>
        ))}
      </ul>

      {hasMore && (
        <LoadingButton
          loading={isValidating}
          onClick={() => loadMoreWithFocus(loadMore)}
          className='mt-5'
          variant='outline'
          size='md'
          type='button'
        >
          {isValidating ? '読み込み中' : 'さらにメンバーを読み込む'}
        </LoadingButton>
      )}
    </>
  );
};
