import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react';
import { Team } from 'genai-web';
import { PiDownloadSimple, PiPencilLine, PiTrash } from 'react-icons/pi';
import { Link } from 'react-router';
import { MoreVertIcon } from '@/components/ui/icons/MoreVertIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/Tooltip';
import { useFocusNewItemOnLoadMore } from '@/hooks/useFocusNewItemOnLoadMore';
import { download } from '@/utils/createDownloadLink';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { useFetchTeamForJsonDownload } from '../hooks/useFetchTeamForJsonDownload';
import { useTeams } from '../hooks/useTeams';

type Props = {
  handleOpenDeleteModal: (team: Team) => void;
};

export const TeamList = (props: Props) => {
  const { handleOpenDeleteModal } = props;
  const { fetchTeamForJsonDownload } = useFetchTeamForJsonDownload();

  const { teams, hasMore, isValidating, loadMore } = useTeams();

  const { listRef, loadMoreWithFocus } = useFocusNewItemOnLoadMore<HTMLUListElement>({
    itemsLength: teams.length,
    focusSelector: 'a',
  });

  if (!isValidating && teams.length === 0) {
    return <div className='mt-4 flex w-full justify-center'>チームが登録されていません</div>;
  }

  return (
    <>
      <h2
        tabIndex={-1}
        id='team-list-heading'
        className={`mt-8 mb-4 inline-flex text-std-18B-160 focus-visible:rounded-4 focus-visible:bg-yellow-300 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:outline-black focus-visible:outline-solid lg:text-std-20B-150`}
      >
        チーム一覧
      </h2>
      <ul ref={listRef} className='flex w-full flex-col'>
        {teams.map((team) => (
          <li
            className='relative grid w-full grid-cols-[1fr_auto] items-center border-b border-solid-gray-420'
            key={team.teamId}
          >
            <div className='px-4 py-3'>
              <Link
                className={`rounded-4 bg-white py-1 text-dns-16N-130 leading-tight! text-blue-1000 underline underline-offset-[calc(3/16*1rem)] hover:decoration-[calc(3/16*1rem)] focus-visible:relative focus-visible:z-10 focus-visible:bg-yellow-300 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:outline-black focus-visible:outline-solid`}
                to={`/teams/${team.teamId}/apps`}
              >
                {team.teamName}
              </Link>
            </div>

            <div className='relative flex flex-none px-2'>
              <Menu>
                <Tooltip placement='left'>
                  <TooltipTrigger asChild>
                    <MenuButton
                      className={`flex size-9 items-center justify-center rounded-4 after:absolute after:-inset-full after:m-auto after:h-11 after:w-11 hover:bg-solid-gray-50 hover:-outline-offset-[calc(2/16*1rem)] hover:outline-black hover:outline-solid focus-visible:bg-yellow-300 focus-visible:ring-[calc(6/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:-outline-offset-4 focus-visible:outline-black focus-visible:outline-solid focus-visible:ring-inset`}
                    >
                      <MoreVertIcon aria-label='チームの操作' role='img' className='mt-0.5' />
                    </MenuButton>
                  </TooltipTrigger>
                  <TooltipContent aria-hidden={true}>チームの操作</TooltipContent>
                </Tooltip>

                <MenuItems
                  modal={false}
                  className={`absolute top-full right-0 z-10 w-auto min-w-fit rounded-8 border border-solid-gray-420 bg-white py-2 shadow-1 focus:outline-hidden`}
                >
                  {team.teamId !== COMMON_EXAPPS_TEAM_ID && (
                  <MenuItem>
                    {({ focus }) => (
                      <Link
                        to={`/teams/${team.teamId}/edit`}
                        className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap text-solid-gray-800 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                      >
                        <PiPencilLine aria-hidden={true} className='text-lg' />
                        チーム名を変更
                      </Link>
                    )}
                  </MenuItem>
                  )}
                  <MenuItem>
                    {({ focus }) => (
                      <button
                        type='button'
                        onClick={async () => {
                          const res = await fetchTeamForJsonDownload(team.teamId);
                          const blob = new Blob([JSON.stringify(res, null, 2)], {
                            type: 'application/json',
                          });
                          const url = URL.createObjectURL(blob);
                          download(url, `${team.teamId}.json`);
                        }}
                        aria-haspopup='dialog'
                        className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:text-solid-gray-800 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                      >
                        <PiDownloadSimple aria-hidden={true} className='text-lg' />
                        JSONダウンロード
                      </button>
                    )}
                  </MenuItem>
                  {team.teamId !== COMMON_EXAPPS_TEAM_ID && (
                  <MenuItem>
                    {({ focus }) => (
                      <button
                        type='button'
                        onClick={() => {
                          handleOpenDeleteModal(team);
                        }}
                        aria-haspopup='dialog'
                        className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap text-error-1 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:text-solid-gray-800 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                      >
                        <PiTrash aria-hidden={true} className='text-lg' />
                        削除
                      </button>
                    )}
                  </MenuItem>
                  )}
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
          {isValidating ? '読み込み中' : 'さらにチームを読み込む'}
        </LoadingButton>
      )}
    </>
  );
};
